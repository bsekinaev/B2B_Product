"""Входные и выходные Pydantic-модели товарной карточки.

Здесь определены ограничения входных данных и структура JSON-ответа.
SEO-тексты и предупреждения проверяет app.validation; статус ручного
ревью не означает разрешение публиковать карточку.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_INPUT_BYTES = 16_384

ProductName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]
SpecName = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120),
]
SpecValue = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, max_length=500),
]
Description = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, max_length=10_000),
]


class ProductInput(BaseModel):
    """Данные прибора, предоставленные пользователем."""

    model_config = ConfigDict(extra="forbid")

    name: ProductName
    manufacturer: ProductName
    specs: dict[SpecName, SpecValue] = Field(default_factory=dict, max_length=50)
    description: Description | None = None

    @field_validator("specs", mode="before")
    @classmethod
    def reject_duplicate_spec_names(cls, value: object) -> object:
        """Не терять характеристики при совпадении ключей после strip()."""
        if not isinstance(value, Mapping):
            return value

        seen: set[str] = set()
        for key in value:
            if not isinstance(key, str):
                continue  # Тип ключа проверит Pydantic.
            normalized_key = key.strip()
            if normalized_key in seen:
                raise ValueError(
                    "Названия характеристик должны быть уникальными после удаления пробелов"
                )
            seen.add(normalized_key)
        return value

    @field_validator("description")
    @classmethod
    def blank_description_to_none(cls, value: str | None) -> str | None:
        """Пустое необязательное описание означает отсутствие данных."""
        return value or None

    @model_validator(mode="after")
    def validate_payload_size(self) -> Self:
        """Ограничить объём нормализованных данных до вызова LLM."""
        if len(self.model_dump_json().encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"Размер данных товара превышает {MAX_INPUT_BYTES} байт")
        return self


class GenerationStatus(StrEnum):
    """Возможные состояния результата генерации."""

    READY_FOR_REVIEW = "ready_for_review"
    INSUFFICIENT_DATA = "insufficient_data"
    REQUIRES_REVISION = "requires_revision"


class ProductCard(BaseModel):
    """Структура карточки; неполные поля допустимы при неуспехе."""

    model_config = ConfigDict(extra="forbid")

    seo_title: str | None = None
    seo_description: str | None = None
    specifications: dict[str, str] = Field(default_factory=dict)
    search_queries: list[str] = Field(default_factory=list)
    commercial_note: str | None = None


class GenerationSource(StrEnum):
    """Фактически выбранный источник SEO-текста."""

    INITIAL_LLM = "initial_llm"
    REFINED_LLM = "refined_llm"
    FALLBACK = "fallback"
    NONE = "none"


class GenerationMeta(BaseModel):
    """Маршрут генерации без промптов и секретов."""

    model_config = ConfigDict(extra="forbid")

    seo_source: GenerationSource
    llm_attempts: int = Field(ge=0)
    reason_codes: list[str] = Field(default_factory=list)


class GenerationResult(BaseModel):
    """JSON-ответ сервиса с результатом и причинами ограничений."""

    model_config = ConfigDict(extra="forbid")

    status: GenerationStatus
    card: ProductCard
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generation_meta: GenerationMeta | None = None
