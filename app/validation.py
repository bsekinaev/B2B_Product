"""Независимая детерминированная проверка черновика B2B-карточки.

Проверки выявляют некоторые неподтверждённые утверждения, но не доказывают
семантическую достоверность текста. ready_for_review означает ручное ревью,
а не разрешение на автоматическую публикацию.
"""

import re
from collections.abc import Iterable

from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput
from app.spec_claims import specification_claim_warnings

SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MIN = 800
SEO_DESCRIPTION_MAX = 1200
SEARCH_QUERIES_MIN = 3
SEARCH_QUERIES_MAX = 5

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SLEEVE_IP = re.compile(r"гильз\w*[^.!?\n]{0,45}\bIP\d{2}\b", re.I)
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Проверяем только высокорисковые утверждения, наличие которых можно
# обнаружить в тексте без языковой модели. Это не полноценный фактчекинг.
_RISKY_CLAIMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bГОСТ\b|\bТУ\b|\bISO\b|сертифик|сертифиц|аттест|госреестр|\bсоответствует\b", re.I
        ),
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
            r"высокоточн|повышенн.{0,12}точност|над[её]жн|долговечн|высок[а-я]{0,10}\s+точност|"
            r"лабораторн|труднодоступн|для.{0,12}точн.{0,15}измерен|"
            r"оперативн.{0,30}отслежива|обеспечива.{0,30}над[её]жн",
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


_RS485_PATTERN = re.compile(
    r"(?<!\w)RS[\s\-‐‑‒–—]*485(?!\w)",
    re.IGNORECASE,
)

_RS485_CONDITION = re.compile(
    r"зависит\s+от\s+(?:исполнения|модификации)"
    r"|в\s+зависимости\s+от\s+(?:исполнения|модификации)"
    r"|(?:в|только\s+в)\s+(?:некоторых|отдельных)"
    r"\s+(?:исполнениях|модификациях)"
    r"|не\s+во\s+всех\s+(?:исполнениях|модификациях)"
    r"|\bопционал\w*",
    re.IGNORECASE,
)


def _optional_rs485_warnings(
    product: ProductInput,
    card: ProductCard,
) -> list[str]:
    """Не разрешать безусловное RS-485 для условного исполнения."""
    optional = any(
        "интерфейс" in name.casefold()
        and _RS485_PATTERN.search(value)
        and ("зависит от исполнения" in value.casefold() or "опционал" in value.casefold())
        for name, value in product.specs.items()
    )

    if not optional:
        return []

    fields = [
        card.seo_title or "",
        card.seo_description or "",
        *card.search_queries,
        card.commercial_note or "",
    ]

    for field in fields:
        for sentence in re.split(r"[.!?;\n]+", field):
            if _RS485_PATTERN.search(sentence) and not _RS485_CONDITION.search(sentence):
                return ["RS-485 указан без ограничения по исполнению"]

    return []


# Узкие проверки подтверждённых предметных дефектов.
# Это защитные сигналы редактору, а не универсальный фактчекинг.

_OUTPUT_DEVICE_GROUP = re.compile(
    r"\b[РКСТИУ]\s*/\s*[РКСТИУ]\s*/\s*[РКСТИУ]",
    re.IGNORECASE,
)

_OUTPUTS_AS_MODES = re.compile(
    r"\bрежим\w*\s+(?:[РКСТИУ]\s*/\s*){2,5}[РКСТИУ]\b",
    re.IGNORECASE,
)

_WALL_DIN_AS_ONE_MOUNT = re.compile(
    r"\bнастенн\w*[^.!?;\n]{0,40}\(\s*Н\s*[,/]\s*DIN\s*\)",
    re.IGNORECASE,
)

_APPLICATION_CLAIM = re.compile(
    r"\b(?:подход\w*|предназнач\w*|применя\w*|использу\w*)\b"
    r"[^.!?\n]{0,100}\b(?:для|в)\b[^.!?\n]*",
    re.IGNORECASE,
)

_NEGATED_APPLICATION = re.compile(
    r"\bне\s+(?:подход\w*|предназнач\w*|применя\w*|использу\w*)\b",
    re.IGNORECASE,
)

_APPLICATION_TERMS = (
    re.compile(r"\bтемператур\w*\b", re.IGNORECASE),
    re.compile(r"\bдавлен\w*\b", re.IGNORECASE),
    re.compile(r"\bуровн\w*\b", re.IGNORECASE),
    re.compile(r"\bвлажност\w*\b", re.IGNORECASE),
    re.compile(r"\bрасход\w*\b", re.IGNORECASE),
)


def _technical_semantics_warnings(
    product: ProductInput,
    card: ProductCard,
) -> list[str]:
    """Сигналы о конкретных неверных технических интерпретациях."""
    warnings: list[str] = []
    text = _all_texts(card)

    output_codes_in_source = any(
        "выходн" in name.casefold() and _OUTPUT_DEVICE_GROUP.search(value)
        for name, value in product.specs.items()
    )

    if output_codes_in_source and _OUTPUTS_AS_MODES.search(text):
        warnings.append("Типы выходных устройств ошибочно названы режимами")

    separate_mounts_in_source = any(
        any(term in name.casefold() for term in ("корпус", "монтаж", "исполнен"))
        and "настенн" in value.casefold()
        and re.search(r"\bDIN\b", value, re.IGNORECASE)
        for name, value in product.specs.items()
    )

    if separate_mounts_in_source and _WALL_DIN_AS_ONE_MOUNT.search(text):
        warnings.append("DIN-реечное исполнение ошибочно названо настенным")

    evidence: list[str] = []

    for sentence in re.split(
        r"(?<=[.!?])\s+|\n+",
        product.description or "",
    ):
        if not _NEGATED_APPLICATION.search(sentence):
            evidence.append(sentence)

    evidence_names = (
        "тип",
        "назначен",
        "применен",
        "измеряем",
        "контролируем",
        "область",
        "поддерживаемые датчики",
    )

    for name, value in product.specs.items():
        if any(term in name.casefold() for term in evidence_names):
            evidence.append(f"{name}: {value}")

    # Однозначный тип прибора подтверждает физическую величину.
    # Это не подтверждает произвольные сценарии применения.
    instrument_type = (f"{product.name} {product.specs.get('тип', '')}").casefold()

    if "манометр" in instrument_type:
        evidence.append("давление")

    supported = "\n".join(evidence)

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if _NEGATED_APPLICATION.search(sentence):
            continue

        claim = _APPLICATION_CLAIM.search(sentence)
        if claim is None:
            continue

        if any(
            term.search(claim.group()) and not term.search(supported) for term in _APPLICATION_TERMS
        ):
            warnings.append("Указана неподтверждённая область применения")
            break

    return warnings


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

    # Число из другой характеристики не подтверждает техническое утверждение.
    warnings.extend(specification_claim_warnings(product, generated))
    warnings.extend(_optional_rs485_warnings(product, card))
    warnings.extend(_technical_semantics_warnings(product, card))

    structured_evidence = _structured_risk_evidence(product)
    for pattern, message in _RISKY_CLAIMS:
        if pattern.search(generated) and not pattern.search(structured_evidence):
            warnings.append(message)

    casing_rating = any(
        "корпус" in name.casefold() and "защит" in name.casefold() for name in product.specs
    )
    sleeve_rating = any(
        "гильз" in name.casefold() and ("степен" in name.casefold() or "ip" in name.casefold())
        for name in product.specs
    )
    if casing_rating and not sleeve_rating and _SLEEVE_IP.search(generated):
        warnings.append("Степень защиты корпуса ошибочно приписана гильзе")

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
