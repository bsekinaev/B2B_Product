"""Регрессионные проверки сборки SEO из исходных параметров."""

import json
from pathlib import Path

import pytest

from app.generator import generate_card
from app.grounded_copy import grounded_seo_description
from app.schemas import GenerationStatus, ProductInput

CASES = [
    {
        "name": "Манометр общетехнический МЕТЕР ДМ 02 (серия)",
        "manufacturer": "МЕТЕР",
        "description": "Манометр для измерения давления.",
        "specs": {
            "тип": "общетехнический манометр",
            "диаметр корпуса": "50 / 63 / 100 / 160 мм, варианты серии",
            "расположение штуцера": "радиальное / осевое, варианты серии",
            "резьба штуцера": "G1/2 / G1/4 / M12x1,5 / M20x1,5, варианты серии",
            "класс точности": "1,5 / 2,5, варианты серии",
            "материал корпуса": "сталь",
            "материал штуцера": "латунь",
            "материал защитного стекла": "пластик / приборное стекло, варианты серии",
            "степень защиты": "IP43",
            "возможность гидрозаполнения": "нет",
            "единицы шкалы": "МПа / кгс/см² / bar",
        },
    },
    {
        "name": "Термометр РОСМА БТ-51.211 (0–100 °C) G1/2.100.1,5",
        "manufacturer": "РОСМА",
        "description": "Биметаллический термометр для измерения температуры.",
        "specs": {
            "тип": "биметаллический термометр",
            "серия": "211",
            "диаметр корпуса": "100 мм",
            "диапазон показаний": "0…+100 °C",
            "присоединение": "осевое",
            "резьба гильзы": "G1/2",
            "длина погружной части": "100 мм",
            "класс точности": "1,5",
            "материал корпуса": "коррозионностойкая сталь",
            "материал штока": "нержавеющая сталь",
            "материал защитной гильзы": "латунь",
            "чувствительный элемент": "биметаллическая спираль",
            "степень защиты корпуса": "IP54",
        },
    },
]


class ShortProvider:
    def __init__(self, product: ProductInput):
        self.product = product
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return json.dumps(
            {
                "seo_title": self.product.name,
                "seo_description": "Краткое описание без характеристик.",
                "search_queries": [
                    self.product.name,
                    f"{self.product.name} характеристики",
                    f"{self.product.name} параметры",
                ],
                "commercial_note": "Гарантия 25 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize("payload", CASES)
def test_grounded_description_meets_length(payload: dict) -> None:
    item = ProductInput.model_validate(payload)
    text = grounded_seo_description(item)

    assert text is not None
    assert 800 <= len(text) <= 1200
    assert "долговечность" not in text.casefold()
    assert "гарантия" not in text.casefold()


@pytest.mark.parametrize("payload", CASES)
def test_grounded_fallback_passes_validation(payload: dict) -> None:
    item = ProductInput.model_validate(payload)
    provider = ShortProvider(item)

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.specifications == item.specs
    assert result.warnings == []
    assert result.missing_fields == []
    assert "Гарантия 25 лет" not in (result.card.commercial_note or "")


def test_sparse_source_does_not_get_padded() -> None:
    item = ProductInput(
        name="Манометр",
        manufacturer="Завод",
        specs={"диапазон": "1 МПа", "диаметр": "100 мм"},
        description="Измерение давления",
    )
    assert grounded_seo_description(item) is None


def test_missing_parameter_disables_fallback() -> None:
    item = ProductInput.model_validate(CASES[1])
    item = item.model_copy(update={"specs": {**item.specs, "дополнительный параметр": ""}})
    assert grounded_seo_description(item) is None


@pytest.mark.parametrize("payload", CASES)
def test_grounded_text_uses_source_purpose(payload: dict) -> None:
    item = ProductInput.model_validate(payload)
    text = grounded_seo_description(item)
    assert text is not None

    purpose = item.description.strip().split(". ", 1)[0]
    assert purpose in text


@pytest.mark.parametrize("payload", CASES)
def test_grounded_text_has_no_internal_editorial_markers(payload: dict) -> None:
    item = ProductInput.model_validate(payload)
    text = grounded_seo_description(item)
    assert text is not None

    assert "В описании сохранены" not in text
    assert "Измерительные и идентификационные параметры" not in text
    assert "Монтажные и габаритные характеристики" not in text
    assert "Конструкция и дополнительные параметры" not in text


@pytest.mark.parametrize(
    ("payload", "expected_parameter"),
    [
        (CASES[0], "класс точности"),
        (CASES[1], "диапазон показаний"),
    ],
)
def test_commercial_prioritizes_selection_parameters(
    payload: dict, expected_parameter: str
) -> None:
    item = ProductInput.model_validate(payload)
    provider = ShortProvider(item)
    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert expected_parameter in (result.card.commercial_note or "")


def test_dense_owen_2trm0_fallback_keeps_all_facts() -> None:
    path = Path(__file__).resolve().parents[1] / "examples/live_batch/products/owen_2trm0.json"
    item = ProductInput.model_validate_json(path.read_text(encoding="utf-8"))

    description = grounded_seo_description(item)

    assert description is not None
    assert 800 <= len(description) <= 1200

    for name, value in item.specs.items():
        assert f"{name} — {value}" in description

    assert "RS-485, зависит от исполнения" in description

    provider = ShortProvider(item)
    result = generate_card(item, provider)

    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []
    assert result.card.specifications == item.specs


def test_overfull_grounded_description_is_not_truncated() -> None:
    item = ProductInput(
        name="Тестовый прибор",
        manufacturer="Тестовый завод",
        specs={f"параметр {index}": "значение " + "А" * 180 for index in range(10)},
        description="Тестовое оборудование.",
    )

    assert grounded_seo_description(item) is None
