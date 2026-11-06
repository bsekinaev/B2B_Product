"""Поисковые запросы из идентификаторов и подтверждённых параметров."""

from app.grounded_copy import _editorial_category
from app.schemas import ProductInput

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

    kind = product.specs.get("тип", "").strip()
    series = any("варианты серии" in value.casefold() for value in product.specs.values())

    candidates = [product.name]

    if kind and "варианты серии" not in kind.casefold():
        candidates.append(f"{product.manufacturer} {kind}")

    candidates.append(f"{product.name} характеристики")

    if names:
        candidates.append(f"{product.name} {names[0]}")

    if series:
        candidates.append(f"{product.name} варианты исполнения")

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
