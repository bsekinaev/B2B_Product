"""Редакторские регрессии коммерческих блоков v0.1.3."""

import json
from pathlib import Path

import pytest

from app.grounded_commercial import (
    _commercial_parameters,
    _source_purpose,
    grounded_commercial_note,
)
from app.grounded_copy import _editorial_category
from app.schemas import ProductInput

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
ITEMS = MANIFEST["items"]


def load(item: dict) -> ProductInput:
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", ITEMS, ids=[item["id"] for item in ITEMS])
def test_commercial_uses_only_existing_selection_names(
    item: dict,
) -> None:
    product = load(item)
    source_specs = dict(product.specs)
    category = _editorial_category(product)

    names = _commercial_parameters(product, list(product.specs), category)
    note = grounded_commercial_note(product, names)

    assert note.strip()
    assert product.specs == source_specs

    for name in names:
        assert name in product.specs
        assert name in note

    if _source_purpose(product.description) is None:
        assert "предназначен для измерения" not in note


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("meter_dm02_series", "манометр"),
        ("rosma_bt_51_211", "термометр"),
        ("owen_2trm1", "измерительного прибора"),
        ("owen_pd200", "преобразователя давления"),
    ],
)
def test_category_specific_commercial_text(
    identifier: str,
    expected: str,
) -> None:
    item = next(item for item in ITEMS if item["id"] == identifier)
    product = load(item)
    note = grounded_commercial_note(product, list(product.specs))

    assert expected in note.casefold()
    assert "параметры:" in note


def test_commercial_openings_are_not_universal() -> None:
    prefixes = {
        grounded_commercial_note(load(item), list(load(item).specs)).split("«", 1)[0]
        for item in ITEMS
    }
    assert len(prefixes) >= 4


def test_negative_purpose_stays_unconfirmed() -> None:
    product = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Завод",
        specs={
            "тип": "манометр",
            "диапазон": "0–1 МПа",
        },
        description=("Манометр не предназначен для измерения давления."),
    )

    note = grounded_commercial_note(product, list(product.specs))

    assert "следует рассматривать" in note
    assert "предназначен для измерения" not in note
    assert "сопоставить с заявкой" in note


def test_unselected_series_limit_remains_explicit() -> None:
    item = next(item for item in ITEMS if item["id"] == "meter_dm02_series")
    product = load(item)

    note = grounded_commercial_note(product, list(product.specs))

    assert "конкретное исполнение" in note
    assert "предел измерения" in note
    assert "варианты серии" not in note


@pytest.mark.parametrize(
    "identifier",
    ["owen_2trm1", "owen_pd150", "owen_pd200"],
)
def test_concise_commercial_for_missing_purpose(
    identifier: str,
) -> None:
    item = next(item for item in ITEMS if item["id"] == identifier)
    product = load(item)

    assert _source_purpose(product.description) is None

    note = grounded_commercial_note(product, list(product.specs))

    assert "параметры:" in note
    assert "используют указанные технические сведения" not in note
    assert "предназначен для измерения" not in note
    assert product.name in note

    if identifier.startswith("owen_pd"):
        assert note.count("При подборе преобразователя давления") == 1


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (
            "meter_dm02_series",
            "Для специалистов по закупке и подбору манометров",
        ),
        (
            "rosma_bt_51_211",
            "Для специалистов по закупке и подбору термометров",
        ),
    ],
)
def test_supported_purpose_has_natural_opening(
    identifier: str,
    expected: str,
) -> None:
    item = next(item for item in ITEMS if item["id"] == identifier)
    product = load(item)

    note = grounded_commercial_note(product, list(product.specs))

    assert expected in note
    assert "предназначен для измерения" in note
