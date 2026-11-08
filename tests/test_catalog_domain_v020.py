"""V020-01: инварианты исходных характеристик, серии и исполнения."""

import pytest
from pydantic import ValidationError

from app.catalog_domain import (
    CatalogDraft,
    CatalogFact,
    CatalogSource,
    SourceKind,
    SourceScope,
)
from app.schemas import ProductInput


def product() -> ProductInput:
    return ProductInput(
        name="ОВЕН ТРМ202",
        manufacturer="ОВЕН",
        specs={"Измерительных каналов": "2", "Интерфейс": "RS-485"},
        description="Данные из документации производителя.",
    )


def source(**overrides: str) -> CatalogSource:
    data = {
        "source_id": "catalog_owen",
        "kind": SourceKind.MANUFACTURER_CATALOG,
        "title": "Каталог производителя",
        "uri": "https://example.org/catalog/trm202",
    }
    data.update(overrides)
    return CatalogSource.model_validate(data)


def draft(**overrides: object) -> CatalogDraft:
    item = product()
    data = {
        "product": item,
        "source_scope": SourceScope.SERIES,
        "sources": (source(),),
        "facts": (
            CatalogFact(name=name, raw_value=value, source_id="catalog_owen")
            for name, value in item.specs.items()
        ),
    }
    data["facts"] = tuple(data["facts"])
    data.update(overrides)
    return CatalogDraft.model_validate(data)


def test_series_preserves_specifications_and_reference() -> None:
    item = draft()
    assert item.source_scope == SourceScope.SERIES
    assert [fact.name for fact in item.facts] == list(item.product.specs)
    assert {fact.name: fact.raw_value for fact in item.facts} == item.product.specs
    assert item.sources[0].uri == "https://example.org/catalog/trm202"


def test_configured_variant_requires_name_and_keeps_scope() -> None:
    item = draft(
        source_scope=SourceScope.CONFIGURED_VARIANT,
        variant_name="ТРМ202-У2",
    )
    assert item.variant_name == "ТРМ202-У2"
    assert item.source_scope == SourceScope.CONFIGURED_VARIANT


@pytest.mark.parametrize(
    "bad_uri",
    [
        "",
        "http://example.org/catalog",
        "https://",
        "https://user:pass@example.org",
        "https://example.org/catalog#fragment",
        "https://example.org/a b",
        "https://example.org:invalid/path",
        "https://example.org:8080/data",
        "https://example.org/\n",
        "x" * 2049,
    ],
)
def test_unsafe_or_invalid_source_uri_is_rejected(bad_uri: str) -> None:
    with pytest.raises(ValidationError):
        source(uri=bad_uri)


def test_source_with_https_default_or_explicit_port_is_allowed() -> None:
    assert source(uri="https://example.org").uri == "https://example.org"
    assert source(uri="https://example.org:443/path").uri.endswith("/path")


def test_document_hash_is_valid_evidence_without_uri() -> None:
    item = source(uri=None, document_sha256="a" * 64)
    assert item.document_sha256 == "a" * 64


@pytest.mark.parametrize("bad_hash", ["abc", "G" * 64, "a" * 63])
def test_bad_document_hash_is_rejected(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        source(uri=None, document_sha256=bad_hash)


def test_source_requires_reference_or_hash() -> None:
    with pytest.raises(ValidationError):
        source(uri=None)


def test_series_cannot_claim_specific_variant() -> None:
    with pytest.raises(ValidationError):
        draft(variant_name="ТРМ202-У2")


def test_configured_variant_must_have_explicit_name() -> None:
    with pytest.raises(ValidationError):
        draft(source_scope=SourceScope.CONFIGURED_VARIANT)


def test_duplicate_source_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        draft(sources=(source(), source(title="Повторный источник")))


def test_fact_cannot_reference_unknown_source() -> None:
    with pytest.raises(ValidationError):
        draft(
            facts=(
                CatalogFact(
                    name="Измерительных каналов",
                    raw_value="2",
                    source_id="unknown_ref",
                ),
                CatalogFact(name="Интерфейс", raw_value="RS-485", source_id="catalog_owen"),
            )
        )


def test_fact_value_must_match_input_exactly() -> None:
    with pytest.raises(ValidationError):
        draft(
            facts=(
                CatalogFact(
                    name="Измерительных каналов",
                    raw_value="3",
                    source_id="catalog_owen",
                ),
                CatalogFact(name="Интерфейс", raw_value="RS-485", source_id="catalog_owen"),
            )
        )


def test_missing_or_extra_fact_is_rejected() -> None:
    with pytest.raises(ValidationError):
        draft(facts=(CatalogFact(name="Интерфейс", raw_value="RS-485", source_id="catalog_owen"),))
    with pytest.raises(ValidationError):
        draft(
            facts=(
                *draft().facts,
                CatalogFact(name="Выдуманный параметр", raw_value="1", source_id="catalog_owen"),
            )
        )


def test_case_insensitive_duplicates_are_rejected() -> None:
    item = ProductInput(
        name="Прибор",
        manufacturer="Изготовитель",
        specs={"Резьба": "М20", "резьба": "М22"},
    )
    with pytest.raises(ValidationError):
        CatalogDraft.from_product(
            product=item,
            source_scope=SourceScope.SERIES,
            sources=(source(),),
            attribute_sources={"Резьба": "catalog_owen", "резьба": "catalog_owen"},
        )


def test_from_product_requires_explicit_evidence_for_every_fact() -> None:
    with pytest.raises(ValueError, match="источник"):
        CatalogDraft.from_product(
            product=product(),
            source_scope=SourceScope.SERIES,
            sources=(source(),),
            attribute_sources={"Интерфейс": "catalog_owen"},
        )


def test_from_product_rejects_unknown_reference() -> None:
    with pytest.raises(ValidationError):
        CatalogDraft.from_product(
            product=product(),
            source_scope=SourceScope.SERIES,
            sources=(source(),),
            attribute_sources={
                "Измерительных каналов": "another_source",
                "Интерфейс": "catalog_owen",
            },
        )


def test_from_product_round_trip_does_not_modify_existing_api_input() -> None:
    initial = product()
    item = CatalogDraft.from_product(
        product=initial,
        source_scope=SourceScope.SERIES,
        sources=(source(),),
        attribute_sources={name: "catalog_owen" for name in initial.specs},
    )
    restored = item.to_product_input()
    assert restored.model_dump() == initial.model_dump()
    assert restored is not initial
    restored.specs["Интерфейс"] = "Изменено локально"
    assert initial.specs["Интерфейс"] == "RS-485"


def test_raw_fact_can_preserve_original_whitespace_without_normalizing() -> None:
    fact = CatalogFact(name="Интерфейс", raw_value="  RS-485  ", source_id="catalog_owen")
    assert fact.raw_value == "  RS-485  "


def test_incomplete_product_can_be_stored_without_invented_facts() -> None:
    item = CatalogDraft.from_product(
        product=ProductInput(name="Серия", manufacturer="Изготовитель"),
        source_scope=SourceScope.SERIES,
        sources=(source(),),
        attribute_sources={},
    )
    assert not item.facts
    assert not item.product.specs
