"""Сверка двух примеров, включаемых в комплект сдачи."""

import json
from pathlib import Path

import pytest

from app.schemas import GenerationResult, GenerationStatus, ProductInput

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "examples" / "submission"
NAMES = ("meter_dm02_series", "rosma_bt_51_211")


@pytest.mark.parametrize("name", NAMES)
def test_submission_result_contract(name: str) -> None:
    product = ProductInput.model_validate_json(
        (BASE / "products" / f"{name}.json").read_text(encoding="utf-8")
    )
    result = GenerationResult.model_validate_json(
        (BASE / "results" / f"{name}.json").read_text(encoding="utf-8")
    )
    card = result.card

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert not result.warnings
    assert not result.missing_fields
    assert card.specifications == product.specs
    assert 0 < len(card.seo_title or "") <= 70
    assert 800 <= len((card.seo_description or "").strip()) <= 1200
    assert 3 <= len(card.search_queries) <= 5
    assert (card.commercial_note or "").strip()


@pytest.mark.parametrize("name", NAMES)
def test_submission_provenance(name: str) -> None:
    manifest = json.loads((BASE / "provenance.json").read_text(encoding="utf-8"))
    assert manifest["provided_by_employer"] is False
    assert manifest["human_review_required"] is True
    assert "grounded_fallback" in manifest["generation_method"]

    case = next(case for case in manifest["cases"] if case["id"] == name)
    assert case["review"] == "human_review_required"
    assert case["catalog_reference"].startswith("https://")


@pytest.mark.parametrize(
    ("stem", "purpose"),
    [
        ("meter_dm02_series", "для измерения давления газообразных"),
        ("rosma_bt_51_211", "для измерения температуры жидкостей"),
    ],
)
def test_submitted_commercial_purpose(stem: str, purpose: str) -> None:
    result = json.loads((BASE / "results" / f"{stem}.json").read_text(encoding="utf-8"))
    note = result["card"]["commercial_note"]

    assert result["status"] == "ready_for_review"
    assert purpose in note
    assert "Гарантия 25 лет" not in note
    assert result["warnings"] == []

    if stem == "meter_dm02_series":
        assert "предел измерения" in note
