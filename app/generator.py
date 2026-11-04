"""Сборка черновика B2B-карточки без передачи характеристик под контроль LLM."""

import json
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, ValidationError

from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode
from app.llm.prompts import (
    DRAFT_RESPONSE_FORMAT,
    SYSTEM_PROMPT,
    build_refinement_prompt,
    build_user_prompt,
)
from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput
from app.validation import (
    SEO_DESCRIPTION_MAX,
    SEO_DESCRIPTION_MIN,
    SEO_TITLE_MAX,
    validate_generated_card,
)


class GeneratedText(BaseModel):
    """Только текстовые поля модели; статус и технические факты сюда не входят."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seo_title: str
    seo_description: str
    search_queries: list[str]
    commercial_note: str


class DuplicateJSONKey(ValueError):
    """JSON не должен молча терять более раннее значение повторного ключа."""


def unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Защитить JSON, включая вложенные объекты, от совпадающих ключей."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey("Repeated JSON key")
        result[key] = value
    return result


def reject_json_constant(value: str) -> None:
    """Не принимать нестандартные JSON-числа NaN и Infinity."""
    raise ValueError("Invalid JSON numeric constant")


def parse_model_json(raw: str) -> GeneratedText:
    """Разобрать ответ модели строго, без Markdown-fence и лишних полей."""
    try:
        content = json.loads(
            raw,
            object_pairs_hook=unique_json_keys,
            parse_constant=reject_json_constant,
        )
        return GeneratedText.model_validate(content)
    except (ValueError, TypeError, ValidationError):
        raise LLMError(LLMErrorCode.BAD_RESPONSE) from None


def _grounded_seo_title(product: ProductInput, proposed: str) -> str:
    """Заменить слишком длинный заголовок названием исходного товара."""
    if len(proposed) <= SEO_TITLE_MAX:
        return proposed
    candidate = f"{product.name} — характеристики"
    return candidate if len(candidate) <= SEO_TITLE_MAX else proposed


def _complete_commercial_note(
    product: ProductInput,
    result: GenerationResult,
    missing: list[str],
) -> GenerationResult:
    """Дополнить пустой коммерческий блок без вымышленных свойств товара."""
    if (result.card.commercial_note or "").strip():
        return result
    if not product.description or sum(bool(x) for x in product.specs.values()) < 3:
        return result

    note = grounded_commercial_note(product, list(product.specs)[:3])
    updated = result.card.model_copy(update={"commercial_note": note})
    return validate_generated_card(product, updated, missing_fields=missing)


def _generate_model_card(product: ProductInput, provider: GigaChatProvider) -> GenerationResult:
    """Собрать черновик и провести независимую проверку качества."""
    specifications = dict(product.specs)
    missing = [f"specs.{name}" for name, value in product.specs.items() if not value]
    card = ProductCard(specifications=specifications)

    # Без технических характеристик генерация недостоверна даже при наличии описания.
    # Не расходуем квоту LLM, когда заведомо не сможем принять результат.
    if not any(value for value in product.specs.values()):
        missing.append("specs")
        if not product.description:
            missing.append("description")
        return GenerationResult(
            status=GenerationStatus.INSUFFICIENT_DATA,
            card=card,
            missing_fields=sorted(set(missing)),
            warnings=["Недостаточно исходных сведений для достоверной генерации"],
        )

    response = provider.generate_text(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(product),
        response_format=deepcopy(DRAFT_RESPONSE_FORMAT),
    )

    # Ошибочный или оборванный JSON не подменяется вымышленным текстом.
    try:
        generated = parse_model_json(response)
    except LLMError as exc:
        if exc.code != LLMErrorCode.BAD_RESPONSE:
            raise
        return GenerationResult(
            status=GenerationStatus.REQUIRES_REVISION,
            card=card,
            missing_fields=missing,
            warnings=["Модель вернула некорректный структурированный ответ"],
        )

    card = ProductCard(
        seo_title=_grounded_seo_title(product, generated.seo_title),
        seo_description=generated.seo_description,
        search_queries=generated.search_queries,
        commercial_note=generated.commercial_note,
        specifications=specifications,
    )
    first = validate_generated_card(product, card, missing_fields=missing)

    # Один ограниченный редакторский повтор, но только когда есть материал
    # для расширения. Он НЕ является повтором сетевой ошибки SDK.
    first_length = len((card.seo_description or "").strip())
    needs_commercial = not (card.commercial_note or "").strip()
    should_revise = (
        first.status == GenerationStatus.REQUIRES_REVISION
        and (first_length < SEO_DESCRIPTION_MIN or needs_commercial)
        and sum(bool(value) for value in product.specs.values()) >= 3
        and bool(product.description)
    )
    if not should_revise:
        return _complete_commercial_note(product, first, missing)

    try:
        revised_raw = provider.generate_text(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_refinement_prompt(
                product, first_length, need_commercial=needs_commercial
            ),
            response_format=deepcopy(DRAFT_RESPONSE_FORMAT),
        )
        revised = parse_model_json(revised_raw)
    except LLMError:
        # Первый корректный черновик остаётся доступен даже при сбое доработки.
        return _complete_commercial_note(product, first, missing)

    revised_length = len(revised.seo_description.strip())
    min_acceptable = SEO_DESCRIPTION_MIN if first_length >= SEO_DESCRIPTION_MIN else first_length
    description_not_worse = min_acceptable <= revised_length <= SEO_DESCRIPTION_MAX
    improved_description = revised_length > first_length
    improved_commercial = needs_commercial and bool(revised.commercial_note.strip())
    if not description_not_worse or not (improved_description or improved_commercial):
        return _complete_commercial_note(product, first, missing)

    revised_card = ProductCard(
        seo_title=_grounded_seo_title(product, revised.seo_title),
        seo_description=revised.seo_description,
        search_queries=revised.search_queries,
        commercial_note=revised.commercial_note,
        specifications=specifications,
    )
    candidate = validate_generated_card(product, revised_card, missing_fields=missing)

    # Не выбирать более длинный ответ ценой новых ошибок или рекламных
    # обещаний. Полноценную смысловую достоверность проверяет редактор.
    if set(candidate.warnings) - set(first.warnings):
        return _complete_commercial_note(product, first, missing)
    return _complete_commercial_note(product, candidate, missing)


def generate_card(
    product: ProductInput,
    provider: GigaChatProvider,
) -> GenerationResult:
    """Использовать LLM, затем проверенный fallback при неудаче."""
    result = _generate_model_card(product, provider)

    if result.status != GenerationStatus.REQUIRES_REVISION:
        return result

    description = grounded_seo_description(product)
    if description is None:
        return result

    title = f"{product.name} — характеристики"
    if len(title) > SEO_TITLE_MAX:
        title = product.name

    if len(title) > SEO_TITLE_MAX:
        return result

    spec_names = list(product.specs)
    priority = (
        "диапазон",
        "класс точности",
        "резьба",
        "присоединение",
        "длина погружной",
        "диаметр",
        "расположение",
        "тип",
        "серия",
    )

    def relevance(name: str) -> tuple[int, int]:
        normalized = name.casefold()
        position = next(
            (index for index, term in enumerate(priority) if term in normalized),
            len(priority),
        )
        return position, spec_names.index(name)

    relevant_names = sorted(spec_names, key=relevance)
    kind = product.specs.get("тип", "")
    queries = [
        product.name,
        f"{product.manufacturer} {kind or product.name}",
        f"{product.name} {relevant_names[0]}",
    ]

    if len({" ".join(q.split()).casefold() for q in queries}) != 3:
        return result

    commercial = grounded_commercial_note(product, relevant_names[:3])

    card = ProductCard(
        seo_title=title,
        seo_description=description,
        search_queries=queries,
        commercial_note=commercial,
        specifications=dict(product.specs),
    )

    candidate = validate_generated_card(product, card, missing_fields=result.missing_fields)

    if candidate.status == GenerationStatus.READY_FOR_REVIEW:
        return candidate

    return result
