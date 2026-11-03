"""Сборка черновика B2B-карточки без передачи характеристик под контроль LLM."""

import json
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, ValidationError

from app.grounded_copy import grounded_commercial_note, grounded_seo_description
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode
from app.llm.prompts import (
    DRAFT_RESPONSE_FORMAT,
    SYSTEM_PROMPT,
    build_refinement_prompt,
    build_user_prompt,
)
from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput
from app.validation import SEO_DESCRIPTION_MAX, SEO_DESCRIPTION_MIN, validate_generated_card


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


def _repair_incomplete_commercial_draft(
    product: ProductInput, result: GenerationResult, missing: list[str]
) -> GenerationResult:
    """Восстановить пустой commercial-блок и короткий текст из исходных фактов.

    Не пытаемся выдавать модельное предположение за проверенную характеристику.
    Применяется только для черновика с пустым коммерческим блоком и при наличии
    как минимум трёх заполненных параметров. Иначе сохраняется requires_revision.
    """
    if result.status != GenerationStatus.REQUIRES_REVISION:
        return result
    if (result.card.commercial_note or "").strip():
        return result
    current_description = (result.card.seo_description or "").strip()
    description = (
        result.card.seo_description
        if SEO_DESCRIPTION_MIN <= len(current_description) <= SEO_DESCRIPTION_MAX
        else grounded_seo_description(product)
    )
    if description is None:
        return result

    revised = result.card.model_copy(
        update={
            "seo_description": description,
            "commercial_note": grounded_commercial_note(product),
        }
    )
    validated = validate_generated_card(product, revised, missing_fields=missing)
    # Если карточка всё ещё требует исправления, сохраняем содержательный
    # проверяемый текст, но не скрываем замечания других проверок.
    return validated


def generate_card(product: ProductInput, provider: GigaChatProvider) -> GenerationResult:
    """Собрать черновик и провести независимую проверку качества."""
    specifications = dict(product.specs)
    missing = [f"specs.{name}" for name, value in product.specs.items() if not value]
    card = ProductCard(specifications=specifications)

    # Совсем без технических сведений генерация длинного SEO-текста недостоверна.
    if not any(value for value in product.specs.values()) and not product.description:
        missing.extend(["specs", "description"])
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
        seo_title=generated.seo_title,
        seo_description=generated.seo_description,
        search_queries=generated.search_queries,
        commercial_note=generated.commercial_note,
        specifications=specifications,
    )
    first = validate_generated_card(product, card, missing_fields=missing)

    # Один ограниченный редакторский повтор, но только когда есть материал
    # для расширения. Он НЕ является повтором сетевой ошибки SDK.
    first_length = len((card.seo_description or "").strip())
    if (
        first.status != GenerationStatus.REQUIRES_REVISION
        or first_length >= SEO_DESCRIPTION_MIN
        or sum(bool(value) for value in product.specs.values()) < 3
        or not product.description
    ):
        return _repair_incomplete_commercial_draft(product, first, missing)

    try:
        revised_raw = provider.generate_text(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_refinement_prompt(product, first_length),
            response_format=deepcopy(DRAFT_RESPONSE_FORMAT),
        )
        revised = parse_model_json(revised_raw)
    except LLMError:
        # Первый корректный черновик остаётся доступен даже при сбое доработки.
        return _repair_incomplete_commercial_draft(product, first, missing)

    revised_length = len(revised.seo_description.strip())
    if not first_length < revised_length <= SEO_DESCRIPTION_MAX:
        return _repair_incomplete_commercial_draft(product, first, missing)

    revised_card = ProductCard(
        seo_title=revised.seo_title,
        seo_description=revised.seo_description,
        search_queries=revised.search_queries,
        commercial_note=revised.commercial_note,
        specifications=specifications,
    )
    candidate = validate_generated_card(product, revised_card, missing_fields=missing)

    # Не выбирать более длинный ответ ценой новых ошибок или рекламных
    # обещаний. Полноценную смысловую достоверность проверяет редактор.
    if set(candidate.warnings) - set(first.warnings):
        return _repair_incomplete_commercial_draft(product, first, missing)
    return _repair_incomplete_commercial_draft(product, candidate, missing)
