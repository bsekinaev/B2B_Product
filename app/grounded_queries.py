"""Поисковые запросы из идентификаторов и подтверждённых параметров."""

import re

from app.editorial_priorities import ranked_spec_names
from app.grounded_copy import _editorial_category
from app.schemas import ProductInput
from app.variant_scope import VariantScope, variant_scope

_CATEGORY_PRIORITIES = {
    "pressure_gauge": (
        "класс точности",
        "диапазон",
        "предел измерения",
        "резьба",
        "диаметр корпуса",
    ),
    "thermometer": (
        "диапазон показаний",
        "класс точности",
        "резьба",
        "длина погружной",
        "присоединение",
    ),
    "pressure_transmitter": (
        "основная погрешность",
        "класс точности",
        "верхние пределы",
        "диапазон",
        "присоединение",
    ),
    "controller": (
        "количество универсальных входов",
        "количество измерительных",
        "количество каналов",
        "типы выходных устройств",
        "входные сигналы",
        "погрешност",
        "напряжение питания",
    ),
    "generic": (
        "диапазон",
        "класс точности",
        "присоединение",
        "питание",
    ),
}

_EXCLUDED = {"тип", "серия", "статус исполнения"}


def _normalize_query(value: str) -> str:
    return " ".join(value.split()).casefold()


def _search_identity(product: ProductInput) -> str:
    """Убрать только служебный суффикс «(серия)», не меняя модель."""
    result = re.sub(r"\s*\(\s*серия\s*\)\s*$", "", product.name, flags=re.I).strip()
    return result or product.name.strip()


def grounded_search_queries(product: ProductInput) -> list[str]:
    """Создать до пяти запросов без вымышленных характеристик.

    Значения альтернативных исполнений не включаются в запросы.
    При недостаточном разнообразии вернуть менее трёх запросов:
    вызывающий генератор должен отказаться от fallback.
    """
    category = _editorial_category(product)
    priorities = _CATEGORY_PRIORITIES[category]

    names = [
        name
        for name, value in product.specs.items()
        if name.casefold() not in _EXCLUDED and value.strip()
    ]

    positions = {name: index for index, name in enumerate(names)}

    def rank(name: str) -> tuple[int, int]:
        normalized = name.casefold()

        priority = next(
            (index for index, term in enumerate(priorities) if term in normalized),
            len(priorities),
        )

        return priority, positions[name]

    names.sort(key=rank)
    if category == "controller":
        preferred = ranked_spec_names(product.specs, category, limit=1)
        if preferred:
            names = preferred + [name for name in names if name not in preferred]

    kind = product.specs.get("тип", "").strip()
    identity = _search_identity(product)
    scope = variant_scope(product)

    candidates = [identity]

    if kind and "варианты серии" not in kind.casefold():
        candidates.append(f"{product.manufacturer} {kind}")

    candidates.append(f"{identity} характеристики")

    if names:
        candidates.append(f"{identity} {names[0]}")

    if scope == VariantScope.EXPLICIT_ALTERNATIVES:
        candidates.append(f"{identity} варианты исполнения")
    elif scope == VariantScope.STATUS_ONLY:
        candidates.append(f"{identity} подбор артикула")

    queries: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        normalized = _normalize_query(candidate)

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        queries.append(" ".join(candidate.split()))

        if len(queries) == 5:
            break

    return queries
