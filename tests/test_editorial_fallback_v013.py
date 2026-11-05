"""V013-04B: category-aware offline fallback regressions."""

import json
from pathlib import Path

import pytest

from app.grounded_copy import (
    _editorial_category,
    grounded_seo_description,
)
from app.schemas import ProductInput

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
ITEMS = MANIFEST["items"]


def load(item: dict) -> ProductInput:
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "item",
    ITEMS,
    ids=[item["id"] for item in ITEMS],
)
def test_fallback_preserves_every_source_spec(item: dict) -> None:
    product = load(item)
    original_specs = dict(product.specs)

    description = grounded_seo_description(product)

    assert description is not None
    assert 800 <= len(description) <= 1200

    for name, value in product.specs.items():
        assert f"{name} — {value.strip()}" in description

    assert product.specs == original_specs
    assert (
        "При выборе исполнения учитывают исходные характеристики и требования к подключению."
    ) not in description


@pytest.mark.parametrize(
    ("identifier", "category"),
    [
        ("meter_dm02_series", "pressure_gauge"),
        ("rosma_bt_51_211", "thermometer"),
        ("owen_2trm1", "controller"),
        ("owen_pd200", "pressure_transmitter"),
    ],
)
def test_product_category_is_based_on_source(
    identifier: str,
    category: str,
) -> None:
    item = next(item for item in ITEMS if item["id"] == identifier)
    assert _editorial_category(load(item)) == category


@pytest.mark.parametrize(
    ("identifier", "heading"),
    [
        ("meter_dm02_series", "Диапазоны и точность измерения:"),
        ("rosma_bt_51_211", "Измерительные показатели:"),
        ("owen_pd200", "Диапазоны и погрешности:"),
    ],
)
def test_category_aware_heading(
    identifier: str,
    heading: str,
) -> None:
    item = next(item for item in ITEMS if item["id"] == identifier)

    description = grounded_seo_description(load(item))

    assert description is not None
    assert heading in description


def test_dense_controller_compact_layout_preserves_facts() -> None:
    """A dense controller may use compact layout to respect SEO length."""
    item = next(item for item in ITEMS if item["id"] == "owen_2trm1")
    product = load(item)

    description = grounded_seo_description(product)

    assert description is not None
    assert 800 <= len(description) <= 1200
    assert "Характеристики:" in description

    for name, value in product.specs.items():
        assert f"{name} — {value.strip()}" in description


def test_short_source_thermometer_is_supported() -> None:
    """Short source description must not disable a factual fallback."""
    path = ROOT / "examples/submission/products/rosma_bt_51_211.json"
    product = ProductInput.model_validate_json(path.read_text(encoding="utf-8")).model_copy(
        update={"description": ("Биметаллический термометр для измерения температуры.")}
    )

    description = grounded_seo_description(product)

    assert description is not None
    assert 800 <= len(description) <= 1200
    assert "При выборе артикула отдельно" in description

    for name, value in product.specs.items():
        assert f"{name} — {value.strip()}" in description


def test_pd200_pressure_limit_is_measurement_parameter() -> None:
    """Pressure limits belong to measurement, not power/interfaces."""
    item = next(item for item in ITEMS if item["id"] == "owen_pd200")
    product = load(item)

    description = grounded_seo_description(product)

    assert description is not None

    measurement = description.split("Диапазоны и погрешности:", 1)[1].split("\n\n", 1)[0]

    electrical = description.split(
        "Электропитание, интерфейсы и дополнительные параметры:",
        1,
    )[1].split("\n\n", 1)[0]

    claim = "верхние пределы избыточного давления — 0,0063…25 МПа"

    assert claim in measurement
    assert claim not in electrical
