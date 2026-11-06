"""Коммерческое пояснение только из предоставленных сведений о товаре."""

import re

from app.grounded_copy import _editorial_category
from app.schemas import ProductInput
from app.variant_scope import VariantScope, variant_scope

_UNSAFE_PURPOSE_CONTEXT = re.compile(
    r"\b(?:"
    r"не\s+(?:для\s+измерения|предназначен\w*|использу\w*|"
    r"применя\w*|подход\w*|пригод\w*|допуска\w*|"
    r"рекоменд\w*|подтвержд\w*)"
    r"|нельзя|запрещено|нет\s+данных|отсутствует\s+подтверждение"
    r"|возможно|вероятно|предположительно|подлежит\s+уточнению"
    r")\b",
    flags=re.IGNORECASE,
)


def _source_purpose(description: str | None) -> str | None:
    """Извлечь прямо указанную задачу измерения без её расширения."""
    if not description:
        return None

    for sentence in re.split(r"(?<=[.!?])\s+", description.strip()):
        match = re.search(r"\bдля измерения\b", sentence, flags=re.IGNORECASE)
        if match is None:
            continue

        # Отрицание или неопределённость в пределах предложения
        # запрещают превращать его в положительное утверждение.
        if _UNSAFE_PURPOSE_CONTEXT.search(sentence):
            continue

        purpose = sentence[match.start() :].strip(" .")
        if 10 <= len(purpose) <= 220:
            return purpose

    return None


_CATEGORY_PRIORITIES = {
    "pressure_gauge": (
        "класс точности",
        "предел измерения",
        "диапазон",
        "резьба",
        "диаметр корпуса",
        "расположение",
    ),
    "thermometer": (
        "диапазон",
        "класс точности",
        "резьба",
        "длина погружной",
        "присоединение",
        "диаметр корпуса",
    ),
    "pressure_transmitter": (
        "погрешност",
        "класс точности",
        "диапазон",
        "предел",
        "присоединение",
        "интерфейс",
    ),
    "controller": (
        "количество универсальных входов",
        "количество измерительных",
        "количество каналов",
        "входные сигналы",
        "типы выходных устройств",
        "интерфейс",
        "напряжение питания",
        "погрешност",
    ),
    "generic": (
        "диапазон",
        "класс точности",
        "присоединение",
        "питание",
    ),
}

_GENERIC_NAMES = {"тип", "серия", "статус исполнения"}


def _commercial_parameters(
    product: ProductInput,
    selection_names: list[str],
    category: str,
) -> list[str]:
    # Only provided, nonempty source specifications are eligible.
    candidates = list(
        dict.fromkeys(
            name
            for name in [*selection_names, *product.specs]
            if name in product.specs and product.specs[name].strip()
        )
    )

    concrete = [name for name in candidates if name.casefold() not in _GENERIC_NAMES]

    if concrete:
        candidates = concrete

    priorities = _CATEGORY_PRIORITIES[category]

    def ranking(name: str) -> tuple[int, int]:
        normalized = name.casefold()
        position = next(
            (index for index, term in enumerate(priorities) if term in normalized),
            len(priorities),
        )
        return position, candidates.index(name)

    return sorted(candidates, key=ranking)[:3]


def _commercial_closing(
    product: ProductInput,
    category: str,
) -> str:
    series = any("варианты серии" in value.casefold() for value in product.specs.values())

    if not series:
        return (
            "Перед заказом проверяют параметры конкретного исполнения по технической документации."
        )

    description = (product.description or "").casefold()

    limit_unselected = "предел измерения" in description and any(
        marker in description for marker in ("не выбра", "не указан", "не задан")
    )

    if limit_unselected:
        return (
            "Для серии необходимо уточнить конкретное "
            "исполнение и предел измерения "
            "по технической документации."
        )

    if variant_scope(product) == VariantScope.STATUS_ONLY:
        return (
            "Для серии не выбран конкретный артикул. Перед заказом "
            "сверяют параметры исполнения по документации изготовителя."
        )

    endings = {
        "pressure_gauge": (
            "Для серии выбирают конкретное исполнение "
            "и сверяют сочетание параметров по документации."
        ),
        "thermometer": (
            "Для серии уточняют конкретное исполнение, не объединяя параметры разных модификаций."
        ),
        "pressure_transmitter": (
            "Для серии выбирают конкретное исполнение "
            "по документации: перечисленные варианты "
            "не подтверждают единую конфигурацию."
        ),
        "controller": (
            "Для серии уточняют конкретное исполнение: "
            "альтернативные характеристики нельзя "
            "автоматически объединять в одну конфигурацию."
        ),
        "generic": ("Конкретное исполнение выбирают по технической документации производителя."),
    }

    return endings[category]


def grounded_commercial_note(
    product: ProductInput,
    selection_names: list[str],
) -> str:
    """Составить B2B-блок из исходных параметров и назначения."""
    category = _editorial_category(product)
    purpose = _source_purpose(product.description)
    selected = _commercial_parameters(product, selection_names, category)

    purpose_labels = {
        "pressure_gauge": "и подбору манометров",
        "thermometer": "и подбору термометров",
        "pressure_transmitter": "и подбору преобразователей давления",
        "controller": "и подбору измерительных приборов",
        "generic": "и подбору оборудования",
    }

    direct_labels = {
        "pressure_gauge": "При выборе манометра",
        "thermometer": "При выборе термометра",
        "pressure_transmitter": "При подборе преобразователя давления",
        "controller": "При подборе измерительного прибора",
        "generic": "При подборе оборудования",
    }

    criteria_labels = {
        "pressure_gauge": ("Для согласования заявки на манометр проверяют параметры:"),
        "thermometer": ("Для выбора термометра сопоставляют параметры:"),
        "pressure_transmitter": ("С технической заявкой сопоставляют параметры:"),
        "controller": ("Для технической заявки учитывают параметры:"),
        "generic": ("Для согласования заявки проверяют параметры:"),
    }

    unsafe_context = bool(_UNSAFE_PURPOSE_CONTEXT.search(product.description or ""))

    if purpose:
        opening = (
            f"Для специалистов по закупке {purpose_labels[category]}: "
            f"«{product.name}» предназначен {purpose}."
        )

        if selected:
            criteria = f"{criteria_labels[category]} {', '.join(selected)}."
        else:
            criteria = (
                "Для подбора необходимо сопоставить имеющиеся характеристики с требованиями заявки."
            )

    elif unsafe_context:
        # Preserve the negative/uncertain-purpose safety contract.
        opening = f"«{product.name}» следует рассматривать по указанным исходным характеристикам."

        if selected:
            criteria = (
                f"При подборе следует сопоставить с заявкой параметры: {', '.join(selected)}."
            )
        else:
            criteria = (
                "При подборе следует сопоставить исходные характеристики с требованиями заявки."
            )

    elif selected:
        # With no explicit purpose, lead with verifiable selection
        # parameters instead of generic claims about the product.
        opening = (
            f"{direct_labels[category]} «{product.name}» "
            f"учитывают параметры: {', '.join(selected)}."
        )
        criteria = ""

    else:
        opening = f"«{product.name}» следует рассматривать по указанным исходным характеристикам."
        criteria = (
            "Для подбора необходимо сопоставить имеющиеся характеристики с требованиями заявки."
        )

    conclusion = _commercial_closing(product, category)

    return " ".join(part for part in (opening, criteria, conclusion) if part)
