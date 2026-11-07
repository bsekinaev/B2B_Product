"""Предметная модель каталога до подключения PostgreSQL в версии 0.2.0.

Модели НЕ изменяют контракт /generate и НЕ запрашивают URL источников.
Каждая характеристика имеет явную ссылку на источник; принадлежность
серии либо выбранному исполнению задаётся отдельно.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas import ProductInput


SourceId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_-]{2,79}$"),
]
FactName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120),
]
RawValue = Annotated[str, StringConstraints(strict=True, max_length=500)]
NonEmptyTitle = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]


class SourceScope(StrEnum):
    """Кому принадлежат характеристики: серии либо конкретному исполнению."""

    SERIES = "series"
    CONFIGURED_VARIANT = "configured_variant"


class SourceKind(StrEnum):
    """Вид источника; доверенность источника не выводится из его вида."""

    MANUFACTURER_CATALOG = "manufacturer_catalog"
    TECHNICAL_PASSPORT = "technical_passport"
    MANUAL = "manual"
    OPERATOR_INPUT = "operator_input"


class CatalogSource(BaseModel):
    """Ссылка на доказательство, а не команда скачивать документ."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: SourceId
    kind: SourceKind
    title: NonEmptyTitle
    uri: str | None = None
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("uri")
    @classmethod
    def check_https_reference(cls, value: str | None) -> str | None:
        """Не принимать ссылки с секретами, фрагментами и неверной схемой."""
        if value is None:
            return None
        if (
            not value
            or len(value) > 2048
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("Недопустимый адрес источника")
        try:
            parts = urlsplit(value)
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or parts.port not in (None, 443)
            ):
                raise ValueError("Источник должен использовать безопасный HTTPS-адрес")
        except ValueError:
            raise ValueError("Недопустимый HTTPS-адрес источника") from None
        return value

    @model_validator(mode="after")
    def check_reference_present(self) -> Self:
        if not self.uri and not self.document_sha256:
            raise ValueError("Источник должен содержать HTTPS-адрес либо SHA-256 документа")
        return self


class CatalogFact(BaseModel):
    """Исходное значение со ссылкой на подтверждающий его источник."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: FactName
    raw_value: RawValue
    source_id: SourceId


class CatalogDraft(BaseModel):
    """Проверенный снимок источников и характеристик одного товара."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductInput
    source_scope: SourceScope
    variant_name: NonEmptyTitle | None = None
    sources: tuple[CatalogSource, ...] = Field(min_length=1, max_length=50)
    facts: tuple[CatalogFact, ...] = ()

    @model_validator(mode="after")
    def validate_catalog_invariants(self) -> Self:
        if self.source_scope == SourceScope.SERIES and self.variant_name is not None:
            raise ValueError("Для серии нельзя указывать конкретное исполнение")
        if self.source_scope == SourceScope.CONFIGURED_VARIANT and self.variant_name is None:
            raise ValueError("Для исполнения требуется его наименование")

        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Повторяются идентификаторы источников")

        names = [fact.name for fact in self.facts]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Повторяются названия характеристик")

        if set(names) != set(self.product.specs):
            raise ValueError("Каждая исходная характеристика требует отдельной ссылки на источник")

        for fact in self.facts:
            if fact.source_id not in source_ids:
                raise ValueError("Характеристика ссылается на неизвестный источник")
            if fact.raw_value != self.product.specs[fact.name]:
                raise ValueError("Значение характеристики не совпадает с исходными данными")

        return self

    @classmethod
    def from_product(
        cls,
        *,
        product: ProductInput,
        source_scope: SourceScope,
        sources: tuple[CatalogSource, ...],
        attribute_sources: Mapping[str, str],
        variant_name: str | None = None,
    ) -> CatalogDraft:
        """Создать снимок только по ЯВНО указанному источнику каждой характеристики."""
        if set(attribute_sources) != set(product.specs):
            raise ValueError("Сопоставьте источник каждой характеристике")
        return cls(
            product=product,
            source_scope=source_scope,
            sources=sources,
            facts=tuple(
                CatalogFact(name=name, raw_value=value, source_id=attribute_sources[name])
                for name, value in product.specs.items()
            ),
            variant_name=variant_name,
        )

    def to_product_input(self) -> ProductInput:
        """Вернуть независимую копию без изменения структуры действующего API."""
        return self.product.model_copy(deep=True)
