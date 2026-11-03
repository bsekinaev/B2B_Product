"""Регрессионные проверки независимого оценщика качества карточек."""

import json
from typing import Any

import pytest

from app.generator import generate_card
from app.schemas import GenerationStatus, ProductCard, ProductInput
from app.validation import validate_generated_card


def source(**overrides: Any) -> ProductInput:
    data: dict[str, Any] = {
        "name": "Манометр DM 02",
        "manufacturer": "Манотомь",
        "specs": {
            "диапазон": "0–1,6 МПа",
            "класс точности": "1,5",
            "диаметр": "100 мм",
        },
        "description": "Измерение избыточного давления",
    }
    data.update(overrides)
    return ProductInput(**data)


def valid_description(size: int = 850) -> str:
    phrase = "Манометр используется для измерения избыточного давления; "
    return (phrase * (size // len(phrase) + 1))[:size]


def card(**changes: Any) -> ProductCard:
    data: dict[str, Any] = {
        "seo_title": "Манометр DM 02 — измерение давления",
        "seo_description": valid_description(),
        "search_queries": [
            "манометр DM 02",
            "манометр Манотомь",
            "манометр диапазон 0–1,6 МПа",
        ],
        "commercial_note": "Для контроля избыточного давления",
        "specifications": source().specs,
    }
    data.update(changes)
    return ProductCard(**data)


def test_valid_card_becomes_ready_for_manual_review() -> None:
    result = validate_generated_card(source(), card())
    assert result.status is GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []
    assert result.missing_fields == []
    assert result.card.specifications == source().specs


@pytest.mark.parametrize("length", [800, 1200])
def test_description_boundaries_are_inclusive(length: int) -> None:
    result = validate_generated_card(source(), card(seo_description=valid_description(length)))
    assert result.status is GenerationStatus.READY_FOR_REVIEW


@pytest.mark.parametrize("length", [0, 799, 1201])
def test_description_outside_required_length_requires_revision(length: int) -> None:
    result = validate_generated_card(source(), card(seo_description=valid_description(length)))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("SEO-описание" in warning for warning in result.warnings)


@pytest.mark.parametrize("length", [8, 70])
def test_title_up_to_70_characters_allowed_if_relevant(length: int) -> None:
    value = ("Манометр" + " " * 80)[:length]
    result = validate_generated_card(source(), card(seo_title=value))
    assert result.status is GenerationStatus.READY_FOR_REVIEW


def test_title_longer_than_70_requires_revision() -> None:
    result = validate_generated_card(source(), card(seo_title="Манометр " + "А" * 62))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("70" in warning for warning in result.warnings)


def test_blank_title_requires_revision() -> None:
    result = validate_generated_card(source(), card(seo_title="  "))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("заголовок отсутствует" in warning for warning in result.warnings)


@pytest.mark.parametrize("count", [3, 5])
def test_query_count_3_to_5_allowed(count: int) -> None:
    queries = ["манометр манотомь"]
    queries.extend(
        f"манометр {word}"
        for word in ["параметры", "применение", "диапазон", "прибор"][: count - 1]
    )
    result = validate_generated_card(source(), card(search_queries=queries))
    assert result.status is GenerationStatus.READY_FOR_REVIEW


@pytest.mark.parametrize("count", [2, 6])
def test_invalid_query_count_requires_revision(count: int) -> None:
    queries = [f"манометр вариант {word}" for word in ["а", "б", "в", "г", "д", "е"][:count]]
    result = validate_generated_card(source(), card(search_queries=queries))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("Поисковых запросов" in warning for warning in result.warnings)


def test_duplicate_queries_are_detected_after_casefold_and_whitespace() -> None:
    queries = ["Манометр DM 02", "  манометр   DM 02  ", "манометр Манотомь"]
    result = validate_generated_card(source(), card(search_queries=queries))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("уникальными" in warning for warning in result.warnings)


def test_empty_search_query_requires_revision() -> None:
    result = validate_generated_card(
        source(), card(search_queries=["Манометр", "  ", "манометр 02"])
    )
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("пустыми" in warning for warning in result.warnings)


def test_empty_commercial_note_requires_revision() -> None:
    result = validate_generated_card(source(), card(commercial_note="   "))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("Коммерческий блок" in warning for warning in result.warnings)


def test_title_must_refer_to_product() -> None:
    result = validate_generated_card(source(), card(seo_title="Купить цифровую электронику"))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("название товара" in warning for warning in result.warnings)


def test_queries_must_refer_to_product() -> None:
    result = validate_generated_card(
        source(), card(search_queries=["купить датчик", "датчик цена", "датчик параметры"])
    )
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("Поисковые запросы не отражают" in warning for warning in result.warnings)


def test_new_numeric_value_in_description_blocks_ready_status() -> None:
    result = validate_generated_card(
        source(), card(seo_description=valid_description() + " Гарантия 2027 года.")
    )
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("числа" in warning for warning in result.warnings)
    assert any("гарантия" in warning for warning in result.warnings)


def test_decimal_separator_comma_or_dot_is_equivalent() -> None:
    result = validate_generated_card(
        source(), card(commercial_note="Для диапазона 0–1.6 МПа и контроля давления")
    )
    assert result.status is GenerationStatus.READY_FOR_REVIEW


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Соответствует ГОСТ", "стандарты"),
        ("Сертифицированный прибор", "стандарты"),
        ("Гарантия производителя", "гарантия"),
        ("Доставка со склада", "поставки"),
        ("Поверка выполнена", "поверке"),
        ("Взрывозащищённое исполнение", "защитные"),
    ],
)
def test_unsubstantiated_claim_requires_revision(claim: str, expected: str) -> None:
    result = validate_generated_card(source(), card(commercial_note=claim))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any(expected in warning for warning in result.warnings)


def test_source_supported_high_risk_mention_is_not_automatically_rejected() -> None:
    product = source(specs={**source().specs, "поверка": "выполнена"})
    result = validate_generated_card(
        product, card(commercial_note="Поверка выполнена", specifications=product.specs)
    )
    assert result.status is GenerationStatus.READY_FOR_REVIEW


def test_blank_spec_value_blocks_ready_status() -> None:
    product = source(specs={"диапазон": "0–1,6 МПа", "диаметр": ""})
    result = validate_generated_card(product, card(specifications=product.specs))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert "specs.диаметр" in result.missing_fields


def test_no_specifications_is_insufficient_even_with_long_text() -> None:
    product = source(specs={})
    result = validate_generated_card(product, card(specifications={}))
    assert result.status is GenerationStatus.INSUFFICIENT_DATA
    assert "specs" in result.missing_fields


def test_changes_to_specs_replaced_with_input_facts() -> None:
    product = source()
    changed = card(specifications={"диапазон": "0–10 МПа"})
    result = validate_generated_card(product, changed)
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert result.card.specifications == product.specs
    assert changed.specifications != result.card.specifications
    assert any("восстановлены" in warning for warning in result.warnings)


def test_duplicate_long_sentences_require_revision() -> None:
    repeated = "Манометр используется для контроля давления оборудования. "
    result = validate_generated_card(source(), card(seo_description=repeated * 16))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("повторяются" in warning for warning in result.warnings)


def test_missing_field_list_is_deduplicated() -> None:
    product = source(specs={"диапазон": "0–1,6 МПа", "диаметр": ""})
    result = validate_generated_card(
        product,
        card(specifications=product.specs),
        missing_fields=["specs.диаметр", "specs.диаметр"],
    )
    assert result.missing_fields == ["specs.диаметр"]


def test_source_and_model_not_mutated_by_validator() -> None:
    product = source()
    original = card()
    _ = validate_generated_card(product, original)
    assert original.specifications == product.specs
    assert original.seo_title == "Манометр DM 02 — измерение давления"


def test_whitespace_padding_cannot_bypass_title_limit() -> None:
    result = validate_generated_card(source(), card(seo_title="Манометр" + " " * 70))
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("70" in warning for warning in result.warnings)


def test_whitespace_padding_cannot_bypass_description_limit() -> None:
    result = validate_generated_card(
        source(), card(seo_description=valid_description(800) + " " * 401)
    )
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("SEO-описание" in warning for warning in result.warnings)


class _StaticProvider:
    """Фиксированный структурированный ответ без сетевых вызовов."""

    def __init__(self, data: ProductCard):
        self.content = json.dumps(data.model_dump(exclude={"specifications"}), ensure_ascii=False)

    def generate_text(self, **_kwargs: Any) -> str:
        return self.content


def test_generator_with_valid_text_sets_ready_for_review() -> None:
    product = source()
    result = generate_card(product, _StaticProvider(card()))  # type: ignore[arg-type]
    assert result.status is GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []
    assert result.card.specifications == product.specs


def test_generator_with_unsupported_number_requires_revision() -> None:
    product = source()
    draft = card(commercial_note="Гарантия 2027 года")
    result = generate_card(product, _StaticProvider(draft))  # type: ignore[arg-type]
    assert result.status is GenerationStatus.REQUIRES_REVISION
    assert any("числа" in warning for warning in result.warnings)
