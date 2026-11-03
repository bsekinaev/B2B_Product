"""Независимая детерминированная проверка черновика B2B-карточки.

Проверки выявляют некоторые неподтверждённые утверждения, но не доказывают
семантическую достоверность текста. ready_for_review означает ручное ревью,
а не разрешение на автоматическую публикацию.
"""

import re
from collections.abc import Iterable

from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput

SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MIN = 800
SEO_DESCRIPTION_MAX = 1200
SEARCH_QUERIES_MIN = 3
SEARCH_QUERIES_MAX = 5

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Проверяем только высокорисковые утверждения, наличие которых можно
# обнаружить в тексте без языковой модели. Это не полноценный фактчекинг.
_RISKY_CLAIMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bГОСТ\b|\bТУ\b|\bISO\b|сертифик|сертифиц|аттест|госреестр|соответств", re.I),
        "В тексте упомянуты неподтверждённые стандарты или сертификаты",
    ),
    (re.compile(r"гарант", re.I), "В тексте заявлена неподтверждённая гарантия"),
    (
        re.compile(r"в наличии|со склада|доставк|срок поставк|бесплатн", re.I),
        "В тексте заявлены неподтверждённые условия поставки",
    ),
    (
        re.compile(r"поверк|калибров", re.I),
        "В тексте заявлены неподтверждённые сведения о поверке или калибровке",
    ),
    (
        re.compile(r"взрывозащищ|степен[ьи] защит|\bIP\d{2}\b", re.I),
        "В тексте заявлены неподтверждённые защитные свойства",
    ),
    (
        re.compile(
            r"высокоточн|повышенн.{0,12}точност|надёжн|долговечн|"
            r"лабораторн|труднодоступн|для.{0,12}точн.{0,15}измерен",
            re.I,
        ),
        "В тексте заявлены неподтверждённые преимущества или области применения",
    ),
)


def _normalized_query(value: str) -> str:
    return " ".join(value.split()).casefold()


def _all_texts(card: ProductCard) -> str:
    """Проверять также поисковые запросы и коммерческий блок, не только SEO."""
    return "\n".join(
        [
            card.seo_title or "",
            card.seo_description or "",
            *card.search_queries,
            card.commercial_note or "",
        ]
    )


def _original_facts(product: ProductInput) -> str:
    return "\n".join(
        [
            product.name,
            product.manufacturer,
            product.description or "",
            *(f"{name}: {value}" for name, value in product.specs.items()),
        ]
    )


def _structured_risk_evidence(product: ProductInput) -> str:
    """Свободный description не подтверждает гарантии/сертификаты/условия поставки.

    Инструкции и рекламные обещания в произвольном описании не должны
    автоматически легализовать те же утверждения в тексте LLM.
    Поддержка по структуре всё равно не заменяет проверку человеком.
    """
    return "\n".join(
        [
            product.name,
            product.manufacturer,
            *(f"{name}: {value}" for name, value in product.specs.items()),
        ]
    )


def _source_numbers(text: str) -> set[str]:
    return {match.replace(",", ".") for match in _NUMBER.findall(text)}


def _has_repeated_sentence(description: str) -> bool:
    seen: set[str] = set()
    for sentence in _SENTENCE_END.split(description):
        normalized = _normalized_query(sentence.strip(".!? "))
        if len(normalized) < 30:
            continue
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def _product_keywords(product: ProductInput) -> set[str]:
    """Подсказки релевантности без строгой проверки всей модели артикула."""
    return {token.casefold() for token in _WORD.findall(product.name)}


def validate_generated_card(
    product: ProductInput,
    card: ProductCard,
    *,
    missing_fields: Iterable[str] = (),
) -> GenerationResult:
    """Принять или отклонить черновик без дополнительных вызовов LLM.

    Любая недостаточность или подозрительное утверждение предотвращает
    ready_for_review. При этом поля остаются доступны для ручной правки.
    """
    warnings: list[str] = []
    missing = sorted(set(missing_fields))

    # Defence in depth: технические характеристики принадлежат источнику.
    if card.specifications != product.specs:
        card = card.model_copy(update={"specifications": dict(product.specs)})
        warnings.append("Характеристики восстановлены из исходного товара")

    for name, value in product.specs.items():
        if not value:
            field = f"specs.{name}"
            if field not in missing:
                missing.append(field)

    has_specs = any(product.specs.values())
    if not has_specs:
        missing.append("specs")
        warnings.append("Отсутствуют заполненные технические характеристики")

    title = (card.seo_title or "").strip()
    description = (card.seo_description or "").strip()
    commercial = (card.commercial_note or "").strip()

    if not title:
        warnings.append("SEO-заголовок отсутствует")
    elif len(card.seo_title or "") > SEO_TITLE_MAX:
        warnings.append(f"SEO-заголовок превышает {SEO_TITLE_MAX} символов")

    if not (
        SEO_DESCRIPTION_MIN <= len(description)
        and len(card.seo_description or "") <= SEO_DESCRIPTION_MAX
    ):
        warnings.append(
            f"SEO-описание должно содержать {SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX} символов"
        )

    if _has_repeated_sentence(description):
        warnings.append("В SEO-описании повторяются одинаковые предложения")

    if not SEARCH_QUERIES_MIN <= len(card.search_queries) <= SEARCH_QUERIES_MAX:
        warnings.append(f"Поисковых запросов должно быть {SEARCH_QUERIES_MIN}–{SEARCH_QUERIES_MAX}")

    normalized_queries = [_normalized_query(q) for q in card.search_queries]
    if any(not q for q in normalized_queries):
        warnings.append("Поисковые запросы не должны быть пустыми")
    if len(set(normalized_queries)) != len(normalized_queries):
        warnings.append("Поисковые запросы должны быть уникальными")

    if not commercial:
        warnings.append("Коммерческий блок отсутствует")

    # Подозрительное отсутствие названия товара — сигнал для редактора.
    keywords = _product_keywords(product)
    if keywords and title and not any(word in title.casefold() for word in keywords):
        warnings.append("SEO-заголовок не отражает название товара")
    if (
        keywords
        and normalized_queries
        and not any(any(word in q for word in keywords) for q in normalized_queries)
    ):
        warnings.append("Поисковые запросы не отражают название товара")

    source = _original_facts(product)
    generated = _all_texts(card)

    # Сопоставление чисел — защитный фильтр, но не семантическая проверка
    # зависимости числа от конкретного технического параметра.
    extra_numbers = _source_numbers(generated) - _source_numbers(source)
    if extra_numbers:
        warnings.append("В тексте есть числа, отсутствующие в исходных данных")

    structured_evidence = _structured_risk_evidence(product)
    for pattern, message in _RISKY_CLAIMS:
        if pattern.search(generated) and not pattern.search(structured_evidence):
            warnings.append(message)

    # Отсутствие структурированных технических фактов важнее SEO-формата.
    if not has_specs:
        status = GenerationStatus.INSUFFICIENT_DATA
    elif missing or warnings:
        status = GenerationStatus.REQUIRES_REVISION
    else:
        status = GenerationStatus.READY_FOR_REVIEW

    return GenerationResult(
        status=status,
        card=card,
        missing_fields=sorted(set(missing)),
        warnings=warnings,
    )
