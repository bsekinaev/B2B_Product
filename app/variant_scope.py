"""Объём свидетельств об исполнениях из предоставленных параметров товара.

Не подменяет модель исполнения в БД и не выводит варианты из имени товара.
"""

from enum import StrEnum

from app.schemas import ProductInput


class VariantScope(StrEnum):
    CONFIGURED_VARIANT = "configured_variant"
    STATUS_ONLY = "status_only"
    EXPLICIT_ALTERNATIVES = "explicit_alternatives"


def variant_scope(product: ProductInput) -> VariantScope:
    """Установить только подтверждаемую входными характеристиками область."""
    explicit = any(
        "варианты серии" in value.casefold() and name.casefold() != "статус исполнения"
        for name, value in product.specs.items()
    )
    if explicit:
        return VariantScope.EXPLICIT_ALTERNATIVES

    status_only = any("варианты серии" in value.casefold() for value in product.specs.values())
    if status_only:
        return VariantScope.STATUS_ONLY

    return VariantScope.CONFIGURED_VARIANT
