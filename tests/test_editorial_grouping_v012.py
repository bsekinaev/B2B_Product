"""Регрессия группировки технических параметров в резервном SEO-тексте."""

import json
from pathlib import Path

import pytest

from app.grounded_copy import grounded_seo_description
from app.schemas import ProductInput

PRODUCTS = Path(__file__).resolve().parents[1] / "examples/live_batch/products"


def _product(name: str) -> ProductInput:
    return ProductInput.model_validate(
        json.loads(
            (
                (
                    (PRODUCTS.parent.parent / "submission" / "products")
                    if name in {"meter_dm02_series", "rosma_bt_51_211"}
                    else PRODUCTS
                )
                / f"{name}.json"
            ).read_text(encoding="utf-8")
        )
    )


@pytest.mark.parametrize(
    "name",
    [
        "meter_dm02_series",
        "rosma_bt_51_211",
        "owen_2trm0",
        "owen_2trm1",
        "owen_trm1",
        "owen_trm10",
        "owen_trm12",
        "owen_trm500",
        "owen_trm101",
        "owen_trm138",
        "owen_trm151",
        "owen_trm201",
    ],
)
def test_fallback_preserves_facts_and_length(name: str) -> None:
    product = _product(name)
    description = grounded_seo_description(product)

    assert description is not None
    assert 800 <= len(description) <= 1200
    for key, value in product.specs.items():
        assert f"{key} — {value}" in description


def test_measurement_values_are_not_called_construction_parameters() -> None:
    product = _product("owen_trm201")
    description = grounded_seo_description(product)

    assert description is not None
    assert "Измерительные характеристики:" in description
    measurement = description.split("Измерительные характеристики:", 1)[1].split("\n\n", 1)[0]
    assert "погрешность с термопреобразователями" in measurement
    assert "время опроса измерительного входа" in measurement
    assert "Конструктивные характеристики включают" not in description


def test_output_types_are_not_described_as_modes() -> None:
    product = _product("owen_2trm1")
    description = grounded_seo_description(product)

    assert description is not None
    assert "типы выходных устройств — Р / К / С / Т / И / У" in description
    assert "режимы Р / К / С / Т / И / У" not in description


def test_mechanical_meter_is_not_called_electrical_equipment() -> None:
    product = _product("meter_dm02_series")
    description = grounded_seo_description(product)

    assert description is not None
    assert "Конструкция и материалы:" in description
    assert "Электропитание, интерфейсы" not in description
