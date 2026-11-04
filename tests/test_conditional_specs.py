"""Проверки условной доступности интерфейса RS-485."""

from pathlib import Path

from app.grounded_copy import grounded_seo_description
from app.schemas import GenerationStatus, ProductCard, ProductInput
from app.validation import validate_generated_card


def make_product() -> ProductInput:
    root = Path(__file__).resolve().parents[1]
    path = root / "examples/live_batch/products/owen_2trm0.json"
    return ProductInput.model_validate_json(path.read_text(encoding="utf-8"))


def make_card(product: ProductInput) -> ProductCard:
    description = grounded_seo_description(product)

    assert description is not None
    assert "RS-485, зависит от исполнения" in description

    return ProductCard(
        seo_title=f"{product.name} — характеристики",
        seo_description=description,
        specifications=product.specs,
        search_queries=[
            product.name,
            f"{product.name} характеристики",
            f"{product.name} параметры",
        ],
        commercial_note="Подбор оборудования по исходным параметрам.",
    )


def test_qualified_rs485_is_accepted() -> None:
    product = make_product()
    result = validate_generated_card(product, make_card(product))

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []


def test_unqualified_rs485_in_seo_is_rejected() -> None:
    product = make_product()
    card = make_card(product)

    description = card.seo_description.replace(
        "RS-485, зависит от исполнения",
        "RS-485, поддерживается прибором",
        1,
    )

    assert 800 <= len(description) <= 1200

    card = card.model_copy(update={"seo_description": description})

    result = validate_generated_card(product, card)

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert "RS-485 указан без ограничения по исполнению" in result.warnings


def test_unqualified_rs485_in_commercial_is_rejected() -> None:
    product = make_product()
    card = make_card(product).model_copy(update={"commercial_note": "Прибор поддерживает RS-485."})

    result = validate_generated_card(product, card)

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert "RS-485 указан без ограничения по исполнению" in result.warnings


def test_rs485_in_some_variants_is_accepted() -> None:
    product = make_product()
    card = make_card(product).model_copy(
        update={"commercial_note": ("RS-485 доступен в некоторых модификациях.")}
    )

    result = validate_generated_card(product, card)

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []
