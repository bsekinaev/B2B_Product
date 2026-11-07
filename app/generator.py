"""Сборка черновика B2B-карточки без передачи характеристик под контроль LLM."""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.grounded_queries import grounded_search_queries
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode
from app.llm.prompts import (
    DRAFT_RESPONSE_FORMAT,
    SYSTEM_PROMPT,
    build_refinement_prompt,
    build_user_prompt,
)
from app.schemas import (
    GenerationMeta,
    GenerationResult,
    GenerationSource,
    GenerationStatus,
    ProductCard,
    ProductInput,
)
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


@dataclass
class _GenerationTrace:
    """Решения генератора без содержимого запросов к модели."""

    seo_source: GenerationSource = GenerationSource.NONE
    llm_attempts: int = 0
    reason_codes: list[str] = field(default_factory=list)

    def attach(self, result: GenerationResult) -> GenerationResult:
        meta = GenerationMeta(
            seo_source=self.seo_source,
            llm_attempts=self.llm_attempts,
            reason_codes=self.reason_codes.copy(),
        )
        return result.model_copy(update={"generation_meta": meta})


class _CountingProvider:
    """Считать логические обращения к generate_text."""

    def __init__(self, delegate: GigaChatProvider, trace: _GenerationTrace):
        self.delegate = delegate
        self.trace = trace

    def generate_text(self, **kwargs: Any) -> str:
        self.trace.llm_attempts += 1
        return self.delegate.generate_text(**kwargs)


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


def _quarantine_commercial_draft(
    product: ProductInput,
    result: GenerationResult,
    missing: list[str],
    trace: _GenerationTrace,
) -> GenerationResult:
    """Keep valid model SEO for manual editing, never auto-approve a risky answer.

    Unlike v1, an unsupported commercial claim always remains a BLOCKING
    requires_revision. The generated note is replaced with a source-grounded
    candidate, but the original validation warnings are retained as evidence.
    """
    if result.status != GenerationStatus.REQUIRES_REVISION:
        return result
    if not result.warnings or result.missing_fields:
        return result
    if len(product.specs) < 8 or not product.description:
        return result
    if not (result.card.commercial_note or "").strip():
        return result

    seo = (result.card.seo_description or "").strip()
    if not SEO_DESCRIPTION_MIN <= len(seo) <= SEO_DESCRIPTION_MAX:
        return result

    grounded = grounded_commercial_note(product, list(product.specs)[:3])
    if grounded == result.card.commercial_note:
        return result

    candidate = validate_generated_card(
        product,
        result.card.model_copy(update={"commercial_note": grounded}),
        missing_fields=missing,
    )
    if candidate.status != GenerationStatus.READY_FOR_REVIEW or candidate.warnings:
        return result

    # Preserve original warning categories for audit/security. The warnings
    # explicitly refer to the original LLM answer, not to the repaired draft.
    trace.reason_codes.append("commercial_quarantined")
    return GenerationResult(
        status=GenerationStatus.REQUIRES_REVISION,
        card=candidate.card,
        missing_fields=result.missing_fields.copy(),
        warnings=[f"Исходный коммерческий блок модели: {warning}" for warning in result.warnings],
    )


def _generate_model_card(
    product: ProductInput,
    provider: GigaChatProvider,
    trace: _GenerationTrace,
) -> GenerationResult:
    """Собрать черновик и провести независимую проверку качества."""
    specifications = dict(product.specs)
    missing = [f"specs.{name}" for name, value in product.specs.items() if not value]
    card = ProductCard(specifications=specifications)

    # Без заполненных характеристик генерация недостоверна.
    # Описание само по себе не оправдывает обращение к LLM.
    if not any(value for value in product.specs.values()):
        trace.reason_codes.append("insufficient_specs")
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
        trace.reason_codes.append("invalid_llm_json")
        return GenerationResult(
            status=GenerationStatus.REQUIRES_REVISION,
            card=card,
            missing_fields=missing,
            warnings=["Модель вернула некорректный структурированный ответ"],
        )

    trace.seo_source = GenerationSource.INITIAL_LLM
    card = ProductCard(
        seo_title=_grounded_seo_title(product, generated.seo_title),
        seo_description=generated.seo_description,
        search_queries=generated.search_queries,
        commercial_note=generated.commercial_note,
        specifications=specifications,
    )
    first = validate_generated_card(product, card, missing_fields=missing)

    # LLM-01 v2: preserve a safe-to-edit SEO draft, but NEVER lift the
    # blocking status of unsupported claims in the original model answer.
    if first.status == GenerationStatus.REQUIRES_REVISION:
        quarantined = _quarantine_commercial_draft(product, first, missing, trace)
        if "commercial_quarantined" in trace.reason_codes:
            return quarantined

    # Один ограниченный редакторский повтор, но только когда есть материал
    # для расширения. Он НЕ является повтором сетевой ошибки SDK.
    first_length = len((card.seo_description or "").strip())
    needs_commercial = not (card.commercial_note or "").strip()
    needs_shortening = first_length > SEO_DESCRIPTION_MAX
    should_revise = (
        first.status == GenerationStatus.REQUIRES_REVISION
        and (first_length < SEO_DESCRIPTION_MIN or needs_shortening or needs_commercial)
        and sum(bool(value) for value in product.specs.values()) >= 3
        and bool(product.description)
    )
    if not should_revise:
        return _complete_commercial_note(product, first, missing)

    if first_length < SEO_DESCRIPTION_MIN:
        trace.reason_codes.append("seo_too_short")
    if needs_shortening:
        trace.reason_codes.append("seo_too_long")
    if needs_commercial:
        trace.reason_codes.append("commercial_missing")
    trace.reason_codes.append("refinement_requested")

    try:
        revised_raw = provider.generate_text(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_refinement_prompt(
                product,
                first_length,
                need_commercial=needs_commercial,
                overlong=needs_shortening,
            ),
            response_format=deepcopy(DRAFT_RESPONSE_FORMAT),
        )
        revised = parse_model_json(revised_raw)
    except LLMError:
        # Первый корректный черновик остаётся доступен даже при сбое доработки.
        trace.reason_codes.append("refinement_failed")
        return _complete_commercial_note(product, first, missing)

    revised_length = len(revised.seo_description.strip())
    min_acceptable = SEO_DESCRIPTION_MIN if first_length >= SEO_DESCRIPTION_MIN else first_length
    description_not_worse = min_acceptable <= revised_length <= SEO_DESCRIPTION_MAX
    improved_description = revised_length > first_length or (
        needs_shortening and SEO_DESCRIPTION_MIN <= revised_length <= SEO_DESCRIPTION_MAX
    )
    improved_commercial = needs_commercial and bool(revised.commercial_note.strip())
    if not description_not_worse or not (improved_description or improved_commercial):
        trace.reason_codes.append("refinement_rejected")
        return _complete_commercial_note(product, first, missing)

    revised_card = ProductCard(
        seo_title=_grounded_seo_title(product, revised.seo_title),
        seo_description=revised.seo_description,
        search_queries=revised.search_queries,
        commercial_note=revised.commercial_note,
        specifications=specifications,
    )
    candidate = validate_generated_card(product, revised_card, missing_fields=missing)

    # An overlong draft is accepted only if the revised response passes ALL
    # existing checks. Never trade a length fix for unsupported claims.
    if needs_shortening and candidate.status != GenerationStatus.READY_FOR_REVIEW:
        trace.reason_codes.append("refinement_rejected")
        return _complete_commercial_note(product, first, missing)

    # Не выбирать более длинный ответ ценой новых ошибок или рекламных
    # обещаний. Полноценную смысловую достоверность проверяет редактор.
    if set(candidate.warnings) - set(first.warnings):
        trace.reason_codes.append("refinement_rejected")
        return _complete_commercial_note(product, first, missing)

    trace.seo_source = GenerationSource.REFINED_LLM
    trace.reason_codes.append(
        "refinement_selected"
        if candidate.status == GenerationStatus.READY_FOR_REVIEW
        else "refinement_partial"
    )
    return _complete_commercial_note(product, candidate, missing)


def generate_card(
    product: ProductInput,
    provider: GigaChatProvider,
) -> GenerationResult:
    """Использовать LLM, затем проверенный fallback при неудаче."""
    trace = _GenerationTrace()
    counted_provider = _CountingProvider(provider, trace)
    result = _generate_model_card(product, counted_provider, trace)

    # A quarantined draft stays requires_revision. The editorial user must
    # approve/replace it; no automatic fallback may silently clear its warning.
    if "commercial_quarantined" in trace.reason_codes:
        return trace.attach(result)

    if result.status != GenerationStatus.REQUIRES_REVISION:
        return trace.attach(result)

    description = grounded_seo_description(product)
    if description is None:
        trace.reason_codes.append("fallback_unavailable")
        return trace.attach(result)

    title = f"{product.name} — характеристики"
    if len(title) > SEO_TITLE_MAX:
        title = product.name

    if len(title) > SEO_TITLE_MAX:
        trace.reason_codes.append("fallback_unavailable")
        return trace.attach(result)

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
    queries = grounded_search_queries(product)

    if not 3 <= len(queries) <= 5:
        trace.reason_codes.append("fallback_unavailable")
        return trace.attach(result)

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
        trace.seo_source = GenerationSource.FALLBACK
        trace.reason_codes.append("fallback_selected")
        return trace.attach(candidate)

    trace.reason_codes.append("fallback_rejected")
    return trace.attach(result)
