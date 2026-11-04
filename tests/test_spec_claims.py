"""Проверка привязки чисел и обозначений к исходным характеристикам."""

import json
from pathlib import Path

import pytest

from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput
from app.validation import validate_generated_card

ROOT = Path(__file__).resolve().parents[1]


def product() -> ProductInput:
    return ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Тестовый завод",
        specs={
            "диапазон измерений": "0–10 МПа",
            "диаметр корпуса": "100 мм",
            "класс точности": "1,5",
            "резьба штуцера": "G1/2 / M12x1,5",
            "резьба гильзы": "G1/4",
            "длина гильзы": "100 мм",
        },
        description="Прибор для измерения давления.",
    )


def make_card(item: ProductInput, claim: str) -> ProductCard:
    phrase = "Манометр предназначен для контроля давления оборудования; "
    seo = (phrase * 20)[:850]

    return ProductCard(
        seo_title="Манометр ТЕСТ",
        seo_description=seo,
        search_queries=[
            "Манометр ТЕСТ",
            "Манометр ТЕСТ характеристики",
            "Манометр ТЕСТ параметры",
        ],
        commercial_note=claim,
        specifications=dict(item.specs),
    )


@pytest.mark.parametrize(
    ("claim", "message"),
    [
        ("Диапазон 100 МПа", "Значение диапазона"),
        ("Предел измерения 100 МПа", "Значение диапазона"),
        ("Диаметр корпуса 10 мм", "Значение диаметра"),
        ("Диаметр корпуса 100 см", "Значение диаметра"),
        ("Диаметр гильзы 100 мм", "Значение диаметра"),
        ("Класс точности 100", "Класс точности"),
        ("Класс точности 10", "Класс точности"),
        ("Резьба штуцера G1/4", "Обозначение резьбы"),
        ("Диапазон 0–10 кПа", "Значение диапазона"),
        ("Класс точности 1,6", "Класс точности"),
    ],
)
def test_cross_parameter_claim_is_rejected(claim: str, message: str) -> None:
    item = product()
    result = validate_generated_card(item, make_card(item, claim))

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any(message in warning for warning in result.warnings)
    assert result.card.specifications == item.specs


@pytest.mark.parametrize(
    "claim",
    [
        "Диапазон 0–10 МПа",
        "Диапазона от 0 до 10 МПа",
        "Диаметр корпуса 100 мм",
        "Класс точности 1.5",
        "Резьба штуцера G1/2",
        "Резьба штуцера M12x1.5",
        "Резьба гильзы G1/4",
    ],
)
def test_supported_claim_remains_valid(claim: str) -> None:
    item = product()
    result = validate_generated_card(item, make_card(item, claim))

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []


@pytest.mark.parametrize(
    "stem",
    ["meter_dm02_series", "rosma_bt_51_211"],
)
def test_submission_examples_still_pass_validation(stem: str) -> None:
    base = ROOT / "examples" / "submission"

    item = ProductInput.model_validate(
        json.loads((base / "products" / f"{stem}.json").read_text(encoding="utf-8"))
    )

    saved = GenerationResult.model_validate(
        json.loads((base / "results" / f"{stem}.json").read_text(encoding="utf-8"))
    )

    actual = validate_generated_card(item, saved.card)

    assert actual.status == GenerationStatus.READY_FOR_REVIEW
    assert actual.warnings == []
