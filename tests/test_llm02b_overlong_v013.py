"""LLM-02B: one bounded shortening retry for an overlong model SEO draft."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.grounded_queries import grounded_search_queries
from app.llm.client import LLMError, LLMErrorCode
from app.llm.prompts import DRAFT_RESPONSE_FORMAT, SYSTEM_PROMPT, build_refinement_prompt
from app.schemas import GenerationSource, GenerationStatus, ProductInput

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


def answer(product: ProductInput, *, overlong: bool = False, note: str | None = None) -> str:
    seo = grounded_seo_description(product)
    assert seo is not None
    assert 800 <= len(seo) <= 1200
    if overlong:
        seo += "\n\n" + "Перед заказом сверяют параметры по документации производителя. " * 12
        assert len(seo) > 1200
    title = f"{product.name} — характеристики"
    if len(title) > 70:
        title = product.name
    return json.dumps(
        {
            "seo_title": title,
            "seo_description": seo,
            "search_queries": grounded_search_queries(product),
            "commercial_note": (
                grounded_commercial_note(product, list(product.specs)[:3]) if note is None else note
            ),
        },
        ensure_ascii=False,
    )


class Provider:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def generate_text(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError("Unexpected third model call")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.parametrize("identifier", IDS)
def test_one_overlong_retry_selects_safe_shortened_llm(identifier: str) -> None:
    product = load(identifier)
    provider = Provider(answer(product, overlong=True), answer(product))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    expected = json.loads(answer(product))
    assert len(provider.calls) == 2
    assert provider.calls[1]["response_format"] == DRAFT_RESPONSE_FORMAT
    assert "превышал 1200 символов" in provider.calls[1]["user_prompt"]
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.seo_description == expected["seo_description"]
    assert result.card.specifications == product.specs
    assert not result.warnings
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.REFINED_LLM
    assert result.generation_meta.llm_attempts == 2
    assert "seo_too_long" in result.generation_meta.reason_codes
    assert "refinement_selected" in result.generation_meta.reason_codes
    assert "fallback_selected" not in result.generation_meta.reason_codes


@pytest.mark.parametrize("identifier", IDS)
def test_second_still_overlong_uses_existing_fallback(identifier: str) -> None:
    product = load(identifier)
    provider = Provider(answer(product, overlong=True), answer(product, overlong=True))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert len(provider.calls) == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert "refinement_rejected" in result.generation_meta.reason_codes
    assert "fallback_selected" in result.generation_meta.reason_codes
    assert result.card.specifications == product.specs


@pytest.mark.parametrize("identifier", IDS)
def test_second_with_unsafe_commercial_must_not_be_approved(identifier: str) -> None:
    product = load(identifier)
    provider = Provider(answer(product, overlong=True), answer(product, note="Гарантия 25 лет."))
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert len(provider.calls) == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source != GenerationSource.REFINED_LLM
    assert "refinement_rejected" in result.generation_meta.reason_codes
    assert "гарант" not in (result.card.commercial_note or "").casefold()
    assert result.card.specifications == product.specs


def test_overlong_retry_transport_failure_keeps_existing_fallback() -> None:
    product = load("owen_trm202")
    provider = Provider(
        answer(product, overlong=True),
        LLMError(LLMErrorCode.RATE_LIMITED, retryable=True),
    )
    result = generate_card(product, provider)  # type: ignore[arg-type]
    assert len(provider.calls) == 2
    assert result.generation_meta is not None
    assert "refinement_failed" in result.generation_meta.reason_codes
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK


def test_overlong_sparse_source_does_not_use_second_call() -> None:
    product = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Завод",
        description="Манометр для измерения давления.",
        specs={"тип": "манометр", "диапазон": "0–1 МПа"},
    )
    payload = {
        "seo_title": product.name,
        "seo_description": "Манометр предназначен для измерения давления. " * 40,
        "search_queries": [
            product.name,
            product.name + " каталог",
            product.name + " характеристики",
        ],
        "commercial_note": "Для проверки требований заявки.",
    }
    provider = Provider(json.dumps(payload, ensure_ascii=False))
    result = generate_card(product, provider)  # type: ignore[arg-type]
    assert len(provider.calls) == 1
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert result.generation_meta is not None
    assert "seo_too_long" not in result.generation_meta.reason_codes


def test_new_prompts_keep_unchanged_schema_and_fact_rules() -> None:
    assert "3–6" in SYSTEM_PROMPT
    assert "полный перечень технических характеристик" in SYSTEM_PROMPT
    assert "Не смешивай характеристики разных исполнений" in SYSTEM_PROMPT
    assert "только факты" not in SYSTEM_PROMPT or "исключительно факты" in SYSTEM_PROMPT
    assert "не выдумывай" in SYSTEM_PROMPT
    assert "specifications" not in DRAFT_RESPONSE_FORMAT["schema"]["properties"]
    normal = build_refinement_prompt(load("owen_trm202"), 360)
    assert "четыре смысловых абзаца" in normal
    assert "превышал 1200 символов" not in normal
    long = build_refinement_prompt(load("owen_trm202"), 1350, overlong=True)
    assert "превышал 1200 символов" in long
    assert "900–1100" in long
