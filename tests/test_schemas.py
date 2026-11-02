"""Unit-тесты Pydantic-схем без обращения к GigaChat API."""

import json

import pytest
from pydantic import ValidationError

from app.schemas import (
    MAX_INPUT_BYTES,
    GenerationResult,
    GenerationStatus,
    ProductCard,
    ProductInput,
)


def valid_product() -> dict[str, object]:
    """Создать независимый валидный набор входных данных."""
    return {
        "name": "Манометр показывающий DM 02",
        "manufacturer": "Манотомь",
        "specs": {
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
            "присоединение": "G1/2",
        },
        "description": "Прибор предназначен для измерения избыточного давления.",
    }


def test_valid_product_preserves_technical_values() -> None:
    product = ProductInput.model_validate(valid_product())

    assert product.name == "Манометр показывающий DM 02"
    assert product.manufacturer == "Манотомь"
    assert product.specs["диапазон измерений"] == "0–1,6 МПа"
    assert product.specs["класс точности"] == "1,5"
    assert product.specs["присоединение"] == "G1/2"


def test_trims_whitespace_without_converting_units() -> None:
    data = valid_product()
    data["name"] = "  Манометр DM 02  "
    data["manufacturer"] = "  Манотомь "
    data["specs"] = {" диапазон измерений ": " 0–1,6 МПа "}
    data["description"] = " Описание "

    product = ProductInput.model_validate(data)

    assert product.name == "Манометр DM 02"
    assert product.manufacturer == "Манотомь"
    assert product.specs == {"диапазон измерений": "0–1,6 МПа"}
    assert product.description == "Описание"


def test_missing_optional_fields_use_safe_defaults() -> None:
    product = ProductInput(name="Манометр", manufacturer="Манотомь")

    assert product.specs == {}
    assert product.description is None


def test_optional_description_accepts_null_and_blank() -> None:
    data = valid_product()
    data["description"] = None
    assert ProductInput.model_validate(data).description is None

    data["description"] = "  "
    assert ProductInput.model_validate(data).description is None


@pytest.mark.parametrize("field", ["name", "manufacturer"])
def test_required_fields_cannot_be_missing(field: str) -> None:
    data = valid_product()
    del data[field]

    with pytest.raises(ValidationError) as error:
        ProductInput.model_validate(data)

    assert field in str(error.value)


@pytest.mark.parametrize("field", ["name", "manufacturer"])
def test_required_fields_cannot_be_blank(field: str) -> None:
    data = valid_product()
    data[field] = "   "

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("name", 123),
        ("manufacturer", True),
        ("specs", []),
        ("specs", {"точность": 1.5}),
        ("specs", {"точность": None}),
        ("description", ["text"]),
    ],
)
def test_wrong_field_types_rejected(field: str, invalid: object) -> None:
    data = valid_product()
    data[field] = invalid

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


@pytest.mark.parametrize(
    "specs",
    [
        {" диапазон ": "0–1,6 МПа", "диапазон": "0–2,5 МПа"},
        {"класс точности": "1,5", "\tкласс точности\t": "2,5"},
        {"диаметр": "100 мм", "диаметр ": "100 мм"},
    ],
)
def test_duplicate_spec_names_after_stripping_rejected(specs: dict[str, str]) -> None:
    """Не допускать молчаливой потери характеристик при нормализации."""
    data = valid_product()
    data["specs"] = specs

    with pytest.raises(ValidationError, match="уникальными"):
        ProductInput.model_validate(data)


def test_json_input_duplicate_spec_names_after_stripping_rejected() -> None:
    """JSON-путь валидации тоже не должен терять характеристики."""
    data = valid_product()
    data["specs"] = {" давление ": "0–1,6 МПа", "давление": "0–2,5 МПа"}

    with pytest.raises(ValidationError, match="уникальными"):
        ProductInput.model_validate_json(json.dumps(data, ensure_ascii=False))


def test_distinct_spec_names_remain_distinct() -> None:
    data = valid_product()
    data["specs"] = {
        "диапазон": "0–1,6 МПа",
        "диапазон измерений": "0–2,5 МПа",
    }

    product = ProductInput.model_validate(data)

    assert len(product.specs) == 2
    assert product.specs["диапазон"] == "0–1,6 МПа"
    assert product.specs["диапазон измерений"] == "0–2,5 МПа"


def test_empty_specification_key_rejected() -> None:
    data = valid_product()
    data["specs"] = {"  ": "100 мм"}

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


def test_empty_specification_value_remains_missing() -> None:
    data = valid_product()
    data["specs"] = {"класс точности": "   "}

    product = ProductInput.model_validate(data)

    assert product.specs == {"класс точности": ""}


def test_unknown_input_fields_rejected() -> None:
    data = valid_product()
    data["temperature"] = "-40 °C"

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


def test_specs_count_limit() -> None:
    data = valid_product()
    data["specs"] = {f"параметр {i}": "значение" for i in range(51)}

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


def test_product_name_length_limit() -> None:
    data = valid_product()
    data["name"] = "М" * 201

    with pytest.raises(ValidationError):
        ProductInput.model_validate(data)


def test_payload_size_limit() -> None:
    data = valid_product()
    data["specs"] = {f"параметр {i}": "x" * 450 for i in range(40)}
    assert len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES

    with pytest.raises(ValidationError, match="Размер данных товара"):
        ProductInput.model_validate(data)


def test_malformed_json_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductInput.model_validate_json('{"name":')


def test_mutable_spec_defaults_are_independent() -> None:
    first = ProductInput(name="Первый", manufacturer="Завод")
    second = ProductInput(name="Второй", manufacturer="Завод")
    first.specs["класс точности"] = "1,5"

    assert second.specs == {}


@pytest.mark.parametrize("status", list(GenerationStatus))
def test_generation_statuses_are_supported(status: GenerationStatus) -> None:
    result = GenerationResult(status=status, card=ProductCard())

    assert result.status == status
    assert result.model_dump(mode="json")["status"] == status.value


def test_partial_output_card_is_allowed() -> None:
    result = GenerationResult(
        status=GenerationStatus.INSUFFICIENT_DATA,
        card=ProductCard(specifications={"диапазон измерений": "0–1,6 МПа"}),
        missing_fields=["description"],
        warnings=["Недостаточно сведений для SEO-описания"],
    )

    assert result.card.seo_description is None
    assert result.card.search_queries == []
    assert result.missing_fields == ["description"]
    assert result.card.specifications["диапазон измерений"] == "0–1,6 МПа"


def test_output_json_round_trip() -> None:
    result = GenerationResult(
        status=GenerationStatus.READY_FOR_REVIEW,
        card=ProductCard(
            seo_title="Манометр DM 02",
            seo_description="Техническое описание",
            specifications={"класс точности": "1,5"},
            search_queries=["манометр DM 02", "манометр Манотомь", "манометр 1,5"],
            commercial_note="Для измерения давления",
        ),
    )

    assert GenerationResult.model_validate_json(result.model_dump_json()) == result


def test_invalid_generation_status_rejected() -> None:
    with pytest.raises(ValidationError):
        GenerationResult(status="published", card=ProductCard())


def test_extra_output_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductCard(seo_title="Манометр", unsupported_field="значение")


def test_mutable_output_defaults_are_independent() -> None:
    first = GenerationResult(
        status=GenerationStatus.REQUIRES_REVISION,
        card=ProductCard(),
    )
    second = GenerationResult(
        status=GenerationStatus.REQUIRES_REVISION,
        card=ProductCard(),
    )
    first.warnings.append("Требуется проверка")
    first.card.search_queries.append("манометр")

    assert second.warnings == []
    assert second.card.search_queries == []
