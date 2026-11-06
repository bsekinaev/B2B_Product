"""LLM-01 v2: keep useful LLM SEO but NEVER auto-accept an unsafe model claim."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.grounded_queries import grounded_search_queries
from app.llm.client import LLMError, LLMErrorCode
from app.schemas import GenerationSource, GenerationStatus, ProductCard, ProductInput
from app.validation import validate_generated_card

ROOT = Path(__file__).resolve().parents[1]
ITEMS = {
    item["id"]: item
    for item in json.loads(
        (ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8")
    )["items"]
}
IDS = ("rosma_bt_51_211", "owen_trm202", "owen_pd200")


def load(identifier: str) -> ProductInput:
    item = ITEMS[identifier]
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


class Provider:
    def __init__(self, *answers: str | LLMError):
        self.answers = list(answers)
        self.calls = 0

    def generate_text(self, **_kwargs: Any) -> str:
        self.calls += 1
        if not self.answers:
            raise AssertionError("Unexpected LLM call")
        answer = self.answers.pop(0)
        if isinstance(answer, LLMError):
            raise answer
        return answer


def fields(product: ProductInput) -> dict[str, object]:
    seo = grounded_seo_description(product)
    assert seo is not None
    seo += "\n\nСводка для технического сравнения."
    assert 800 <= len(seo) <= 1200
    title = f"{product.name} — характеристики"
    if len(title) > 70:
        title = product.name
    return {
        "seo_title": title,
        "seo_description": seo,
        "search_queries": grounded_search_queries(product),
        "commercial_note": grounded_commercial_note(product, list(product.specs)[:3]),
    }


def encode(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize("identifier", IDS)
def test_unsafe_commercial_is_quarantined_not_approved(identifier: str) -> None:
    product = load(identifier)
    before = dict(product.specs)
    draft = fields(product)
    draft["commercial_note"] = "Гарантия 25 лет."
    original = validate_generated_card(
        product,
        ProductCard(specifications=before, **draft),  # type: ignore[arg-type]
    )
    assert original.status == GenerationStatus.REQUIRES_REVISION
    assert any("гарантия" in w for w in original.warnings)

    provider = Provider(encode(draft))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert result.card.seo_description == draft["seo_description"]
    assert result.card.seo_title == draft["seo_title"]
    assert result.card.search_queries == draft["search_queries"]
    assert result.card.specifications == product.specs == before
    assert result.card.commercial_note == grounded_commercial_note(product, list(product.specs)[:3])
    assert "гарант" not in (result.card.commercial_note or "").casefold()
    assert any("исходный" in w.casefold() and "гарантия" in w for w in result.warnings)
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.INITIAL_LLM
    assert "commercial_quarantined" in result.generation_meta.reason_codes
    assert "fallback_selected" not in result.generation_meta.reason_codes
    assert result.generation_meta.llm_attempts == provider.calls == 1


@pytest.mark.parametrize("identifier", IDS)
def test_clean_model_answer_is_unmodified(identifier: str) -> None:
    product = load(identifier)
    draft = fields(product)
    provider = Provider(encode(draft))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.commercial_note == draft["commercial_note"]
    assert result.card.seo_description == draft["seo_description"]
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.INITIAL_LLM
    assert "commercial_quarantined" not in result.generation_meta.reason_codes
    assert provider.calls == 1


@pytest.mark.parametrize("identifier", IDS)
def test_unsafe_seo_is_never_hidden_by_commercial_repair(identifier: str) -> None:
    product = load(identifier)
    draft = fields(product)
    draft["commercial_note"] = "Гарантия 25 лет."
    draft["seo_description"] = str(draft["seo_description"]) + "\n\nГарантия 25 лет."
    assert len(str(draft["seo_description"])) <= 1200
    result = generate_card(product, Provider(encode(draft)))  # type: ignore[arg-type]

    assert result.generation_meta is not None
    assert "commercial_quarantined" not in result.generation_meta.reason_codes
    assert result.card.seo_description != draft["seo_description"]


def test_unsafe_search_queries_are_never_hidden() -> None:
    product = load("owen_trm202")
    draft = fields(product)
    draft["commercial_note"] = "Гарантия 25 лет."
    search = list(draft["search_queries"])
    search[0] += " гарантия 25 лет"
    draft["search_queries"] = search
    result = generate_card(product, Provider(encode(draft)))  # type: ignore[arg-type]

    assert result.generation_meta is not None
    assert "commercial_quarantined" not in result.generation_meta.reason_codes
    assert result.card.search_queries != search


def test_unsupported_numeric_claim_keeps_blocking_status_and_original_warning() -> None:
    product = load("owen_trm202")
    draft = fields(product)
    draft["commercial_note"] = "Гарантия 2027 года."
    result = generate_card(product, Provider(encode(draft)))  # type: ignore[arg-type]
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("числа" in w for w in result.warnings)
    assert result.generation_meta is not None
    assert "commercial_quarantined" in result.generation_meta.reason_codes


def test_short_seo_keeps_existing_refinement() -> None:
    product = load("owen_trm202")
    draft = fields(product)
    draft["seo_description"] = "Краткий черновик."
    draft["commercial_note"] = "Гарантия 25 лет."
    refined = fields(product)
    provider = Provider(encode(draft), encode(refined))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.REFINED_LLM
    assert "commercial_quarantined" not in result.generation_meta.reason_codes
    assert provider.calls == 2


def test_sparse_product_keeps_existing_refusal() -> None:
    product = ProductInput(
        name="Контрольный прибор",
        manufacturer="Завод",
        specs={"тип": "манометр", "диапазон": "0–1 МПа", "класс точности": "1,5"},
        description="Предназначен для измерения давления.",
    )
    draft = {
        "seo_title": product.name,
        "seo_description": "Описание для сравнения параметров. " * 28,
        "search_queries": [
            product.name,
            f"{product.name} характеристики",
            f"{product.name} параметры",
        ],
        "commercial_note": "Гарантия 25 лет.",
    }
    provider = Provider(encode(draft))
    result = generate_card(product, provider)  # type: ignore[arg-type]
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("гарантия" in w for w in result.warnings)
    assert result.generation_meta is not None
    assert "commercial_quarantined" not in result.generation_meta.reason_codes
    assert provider.calls == 1


def test_json_and_rate_limit_behaviour_unchanged() -> None:
    product = load("owen_pd200")
    broken = generate_card(product, Provider("bad json"))  # type: ignore[arg-type]
    assert broken.generation_meta is not None
    assert broken.generation_meta.seo_source == GenerationSource.FALLBACK
    assert "commercial_quarantined" not in broken.generation_meta.reason_codes

    blocked = Provider(LLMError(LLMErrorCode.RATE_LIMITED, retryable=True))
    with pytest.raises(LLMError) as exc:
        generate_card(product, blocked)  # type: ignore[arg-type]
    assert exc.value.code == LLMErrorCode.RATE_LIMITED
    assert blocked.calls == 1
