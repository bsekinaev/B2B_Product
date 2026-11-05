"""Маршруты формирования SEO: начальный ответ, доработка, fallback и отказ без сети."""

import json
from pathlib import Path
from typing import Any

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.schemas import GenerationResult, GenerationSource, GenerationStatus, ProductInput


class SequenceProvider:
    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls = 0

    def generate_text(self, **_kwargs: Any) -> str:
        self.calls += 1
        if not self.responses:
            raise AssertionError("Неожиданный дополнительный вызов модели")
        return self.responses.pop(0)


def product() -> ProductInput:
    path = (
        Path(__file__).resolve().parents[1]
        / "examples/submission/products/rosma_bt_51_211.json"
    )
    return ProductInput.model_validate_json(path.read_text(encoding="utf-8"))


def response(item: ProductInput, description: str, *, commercial: str | None = None) -> str:
    return json.dumps(
        {
            "seo_title": item.name,
            "seo_description": description,
            "search_queries": [
                item.name,
                f"{item.manufacturer} биметаллический термометр",
                f"{item.name} диапазон показаний",
            ],
            "commercial_note": (
                grounded_commercial_note(item, list(item.specs)[:3])
                if commercial is None
                else commercial
            ),
        },
        ensure_ascii=False,
    )


def test_first_model_answer_has_explicit_origin() -> None:
    item = product()
    seo = grounded_seo_description(item)
    assert seo is not None
    provider = SequenceProvider(response(item, seo))

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.INITIAL_LLM
    assert result.generation_meta.llm_attempts == 1
    assert result.generation_meta.reason_codes == []
    assert result.card.seo_description == seo
    assert result.card.specifications == item.specs


def test_refinement_is_recorded_only_when_selected() -> None:
    item = product()
    seo = grounded_seo_description(item)
    assert seo is not None
    provider = SequenceProvider(
        response(item, "Короткое описание", commercial=""),
        response(item, seo),
    )

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.REFINED_LLM
    assert result.generation_meta.llm_attempts == 2
    assert "refinement_selected" in result.generation_meta.reason_codes
    assert result.card.seo_description == seo


def test_fallback_is_recorded_when_both_model_drafts_are_short() -> None:
    item = product()
    provider = SequenceProvider(
        response(item, "Недостаточное описание"),
        response(item, "Короткое описание"),
    )

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert result.generation_meta.llm_attempts == 2
    assert "fallback_selected" in result.generation_meta.reason_codes
    assert result.card.specifications == item.specs


def test_invalid_model_json_reports_no_seo_source_if_fallback_unavailable() -> None:
    item = ProductInput(name="Манометр", manufacturer="Завод", specs={"давление": "1 МПа"})
    provider = SequenceProvider("не JSON")

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.NONE
    assert result.generation_meta.llm_attempts == 1
    assert "invalid_llm_json" in result.generation_meta.reason_codes
    assert "fallback_unavailable" in result.generation_meta.reason_codes
    assert result.card.seo_description is None


def test_no_specs_skips_provider_and_records_reason() -> None:
    item = ProductInput(name="Манометр", manufacturer="Завод")
    provider = SequenceProvider()

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.INSUFFICIENT_DATA
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.NONE
    assert result.generation_meta.llm_attempts == 0
    assert result.generation_meta.reason_codes == ["insufficient_specs"]
    assert provider.calls == 0


def test_legacy_result_remains_parseable_without_generation_meta() -> None:
    old_payload = {
        "status": "insufficient_data",
        "card": {"specifications": {}},
        "warnings": [],
        "missing_fields": ["specs"],
    }

    restored = GenerationResult.model_validate(old_payload)

    assert restored.generation_meta is None
    assert restored.status == GenerationStatus.INSUFFICIENT_DATA
