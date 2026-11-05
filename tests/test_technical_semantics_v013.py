"""Предметные регрессии V013-03, без GigaChat и новых сетевых вызовов."""

import pytest

from app.schemas import ProductCard, ProductInput
from app.validation import validate_generated_card

OUTPUTS_WARNING = "Типы выходных устройств ошибочно названы режимами"
MOUNT_WARNING = "DIN-реечное исполнение ошибочно названо настенным"
APPLICATION_WARNING = "Указана неподтверждённая область применения"
RS485_WARNING = "RS-485 указан без ограничения по исполнению"


def make_product(
    *,
    description: str = "Измеритель для обработки сигналов датчиков.",
    specs: dict[str, str] | None = None,
) -> ProductInput:
    return ProductInput(
        name="ОВЕН ТРМ1",
        manufacturer="ОВЕН",
        description=description,
        specs=specs
        if specs is not None
        else {
            "выходные устройства": "Р / К / С / Т / И / У, варианты серии",
            "исполнения корпуса": ("щитовой Щ1 / настенный Н / DIN, варианты серии"),
            "интерфейс связи": "RS-485, опционально",
        },
    )


def warnings_for(product: ProductInput, text: str) -> list[str]:
    card = ProductCard(
        seo_title=product.name,
        seo_description=text,
        specifications=dict(product.specs),
        search_queries=[
            f"{product.name} характеристики",
            f"{product.name} руководство",
            f"{product.name} параметры",
        ],
        commercial_note="Подбор по исходным техническим характеристикам.",
    )
    result = validate_generated_card(product, card)
    return result.warnings


def test_output_types_are_not_modes() -> None:
    text = "Выбор режимов Р / К / С / Т / И / У."
    assert OUTPUTS_WARNING in warnings_for(make_product(), text)


def test_output_types_described_correctly() -> None:
    text = "Типы выходных устройств: Р / К / С / Т / И / У."
    assert OUTPUTS_WARNING not in warnings_for(make_product(), text)


def test_din_mount_is_not_wall_mounted() -> None:
    text = "Варианты щитового и настенного (Н, DIN) монтажа."
    assert MOUNT_WARNING in warnings_for(make_product(), text)


def test_din_and_wall_mount_are_separate() -> None:
    text = "Настенное исполнение Н и DIN-реечное исполнение отдельно."
    assert MOUNT_WARNING not in warnings_for(make_product(), text)


def test_unconfirmed_applications_are_rejected() -> None:
    product = make_product(
        specs={
            "тип": "измеритель-регулятор",
            "температура эксплуатации": "+1…+50 °С",
        }
    )
    text = "Подходит для задач контроля температуры, давления и уровня."
    assert APPLICATION_WARNING in warnings_for(product, text)


def test_confirmed_application_is_allowed() -> None:
    product = make_product(
        description="Измеритель для контроля давления.",
        specs={"тип": "измеритель-регулятор"},
    )
    text = "Предназначен для контроля давления."
    assert APPLICATION_WARNING not in warnings_for(product, text)


def test_negated_source_is_not_positive_evidence() -> None:
    product = make_product(
        description="Прибор не предназначен для контроля давления.",
        specs={"тип": "измеритель-регулятор"},
    )
    text = "Подходит для контроля давления."
    assert APPLICATION_WARNING in warnings_for(product, text)


def test_negated_output_does_not_claim_capability() -> None:
    product = make_product(specs={"тип": "измеритель-регулятор"})
    text = "Не подходит для контроля давления."
    assert APPLICATION_WARNING not in warnings_for(product, text)


def test_unconditional_optional_rs485_is_rejected() -> None:
    product = make_product(specs={"интерфейс связи": "RS-485, опционально"})
    text = "Интерфейс RS-485 доступен."
    assert RS485_WARNING in warnings_for(product, text)


@pytest.mark.parametrize(
    "text",
    [
        "Интерфейс RS-485 доступен в отдельных исполнениях.",
        "Интерфейс RS-485 опционален.",
    ],
)
def test_qualified_optional_rs485_is_allowed(text: str) -> None:
    product = make_product(specs={"интерфейс связи": "RS-485, опционально"})
    assert RS485_WARNING not in warnings_for(product, text)


def test_batch_manometer_pressure_is_supported() -> None:
    """Воспроизведение корректного манометра из batch runner."""
    product = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Тестовый завод",
        specs={
            "тип": "манометр",
            "диапазон": "0–10 МПа",
            "диаметр корпуса": "100 мм",
            "класс точности": "1,5",
        },
    )

    card = ProductCard(
        seo_title=product.name,
        seo_description=("Манометр предназначен для контроля давления; " * 30)[:850],
        specifications=dict(product.specs),
        search_queries=[
            "Манометр ТЕСТ",
            "Манометр ТЕСТ характеристики",
            "Манометр ТЕСТ параметры",
        ],
        commercial_note="Подбор по исходным характеристикам.",
    )

    result = validate_generated_card(product, card)

    assert result.status.value == "ready_for_review", result.warnings
    assert result.warnings == []


def test_manometer_type_does_not_support_temperature_claim() -> None:
    """Тип манометра не подтверждает другую физическую величину."""
    product = make_product(specs={"тип": "манометр"})

    warnings = warnings_for(
        product,
        "Манометр предназначен для контроля температуры.",
    )

    assert APPLICATION_WARNING in warnings
