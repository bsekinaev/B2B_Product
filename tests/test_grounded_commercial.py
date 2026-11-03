"""Регрессия: назначение и критерии подбора в коммерческих блоках."""

import json
from pathlib import Path

import pytest

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.schemas import GenerationStatus, ProductInput

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/submission/products"


def load_product(stem: str) -> ProductInput:
    data = json.loads((EXAMPLES / f"{stem}.json").read_text(encoding="utf-8"))
    return ProductInput.model_validate(data)


@pytest.mark.parametrize(
    ("stem", "purpose"),
    [
        ("meter_dm02_series", "для измерения давления газообразных"),
        ("rosma_bt_51_211", "для измерения температуры жидкостей"),
    ],
)
def test_commercial_contains_source_purpose(stem: str, purpose: str) -> None:
    product = load_product(stem)
    original_specs = dict(product.specs)

    note = grounded_commercial_note(product, list(product.specs)[:3])

    assert purpose in note
    assert "специалистов по закупке" in note
    assert "параметры:" in note
    assert "гарантия" not in note.casefold()
    assert product.specs == original_specs


def test_series_requires_configuration_and_measurement_limit() -> None:
    product = load_product("meter_dm02_series")

    note = grounded_commercial_note(
        product,
        ["класс точности", "резьба штуцера", "диаметр корпуса"],
    )

    assert "конкретное исполнение" in note
    assert "предел измерения" in note
    assert "варианты серии" not in note


def test_no_unverified_purpose_is_invented() -> None:
    product = ProductInput(
        name="Контрольный прибор",
        manufacturer="Тест",
        specs={"тип": "контрольный прибор"},
        description="Компактное изделие.",
    )

    note = grounded_commercial_note(product, ["тип"])

    assert "предназначен для измерения" not in note
    assert "компактное" not in note.casefold()
    assert "тип" in note


def test_negated_purpose_is_not_reversed() -> None:
    product = ProductInput(
        name="Манометр",
        manufacturer="Тест",
        specs={"тип": "манометр"},
        description="Манометр не предназначен для измерения давления.",
    )

    note = grounded_commercial_note(product, ["тип"])

    assert "предназначен для измерения давления" not in note
    assert "сопоставить с заявкой" in note


class ShortProvider:
    def __init__(self, product: ProductInput):
        self.product = product
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return json.dumps(
            {
                "seo_title": self.product.name,
                "seo_description": "Краткое описание.",
                "search_queries": [
                    self.product.name,
                    f"{self.product.name} характеристики",
                    f"{self.product.name} параметры",
                ],
                "commercial_note": "Гарантия 25 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("meter_dm02_series", "для измерения давления"),
        ("rosma_bt_51_211", "для измерения температуры"),
    ],
)
def test_generator_fallback_uses_grounded_commercial(stem: str, expected: str) -> None:
    product = load_product(stem)
    provider = ShortProvider(product)

    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.specifications == product.specs
    assert 800 <= len(result.card.seo_description or "") <= 1200
    assert expected in (result.card.commercial_note or "")
    assert "Гарантия 25 лет" not in (result.card.commercial_note or "")
    assert result.warnings == []
