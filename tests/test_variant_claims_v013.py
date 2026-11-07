"""V013-03B: variant compatibility regression tests, offline."""

from pathlib import Path

from app.schemas import ProductCard, ProductInput
from app.validation import validate_generated_card
from app.variant_claims import variant_claim_warnings

PRODUCTS = Path(__file__).resolve().parents[1] / "examples/live_batch/products"


def product(identifier: str) -> ProductInput:
    return ProductInput.model_validate_json(
        (PRODUCTS / f"{identifier}.json").read_text(encoding="utf-8")
    )


def card(item: ProductInput, description: str) -> ProductCard:
    return ProductCard(
        seo_title=item.name,
        seo_description=description,
        specifications=dict(item.specs),
        search_queries=[item.name, "характеристики", "параметры"],
        commercial_note="Подбор по исходной документации.",
    )


def warnings(identifier: str, description: str) -> list[str]:
    item = product(identifier)
    return variant_claim_warnings(item, card(item, description))


def test_hart_rs485_simultaneous_is_rejected() -> None:
    item = product("owen_pd200")
    draft = card(
        item,
        "Прибор оснащён одновременно интерфейсами HART и RS-485.",
    )
    result = validate_generated_card(item, draft)

    assert any("Альтернативные интерфейсы" in warning for warning in result.warnings)
    assert result.status.value == "requires_revision"


def test_hart_rs485_alternatives_allowed() -> None:
    assert not warnings(
        "owen_pd200",
        "В серии предусмотрены исполнения с HART или RS-485.",
    )


def test_neutral_list_of_interfaces_allowed() -> None:
    assert not warnings(
        "owen_pd200",
        "Варианты серии включают HART и RS-485.",
    )


def test_negated_simultaneous_claim_allowed() -> None:
    assert not warnings(
        "owen_pd200",
        "HART и RS-485 не работают одновременно.",
    )


def test_wall_din_in_one_variant_rejected() -> None:
    assert any(
        "варианты монтажа" in warning
        for warning in warnings(
            "owen_2trm1",
            "Настенный и DIN-реечный монтаж одновременно доступны в одной модификации.",
        )
    )


def test_wall_din_as_alternatives_allowed() -> None:
    assert not warnings(
        "owen_2trm1",
        "Настенное Н или DIN-реечное Д исполнение.",
    )


def test_unconditional_analog_output_rejected() -> None:
    assert any(
        "Аналоговый выход" in warning
        for warning in warnings(
            "owen_pd150",
            "Аналоговый выход 4…20 мА предусмотрен.",
        )
    )


def test_conditional_analog_output_allowed() -> None:
    assert not warnings(
        "owen_pd150",
        "Аналоговый выход 4…20 мА доступен в отдельных исполнениях.",
    )


def test_wrong_membrane_material_rejected() -> None:
    assert any(
        "Материал одного узла" in warning
        for warning in warnings(
            "owen_pd200",
            "Материал мембраны — алюминиевый сплав ADC12.",
        )
    )


def test_wrong_casing_material_rejected() -> None:
    assert any(
        "Материал одного узла" in warning
        for warning in warnings(
            "owen_pd200",
            "Корпус из нержавеющей стали SS316L.",
        )
    )


def test_correct_materials_allowed() -> None:
    assert not warnings(
        "owen_pd200",
        "Мембрана из SS316L; корпус из ADC12.",
    )


def test_unmarked_options_do_not_trigger_rule() -> None:
    item = ProductInput(
        name="Прибор ТЕСТ",
        manufacturer="Завод",
        specs={"тип": "контроллер"},
    )
    assert not variant_claim_warnings(
        item,
        card(item, "HART и RS-485 работают одновременно."),
    )
