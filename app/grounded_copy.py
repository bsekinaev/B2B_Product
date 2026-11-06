"""Проверяемая сборка SEO из характеристик без новых технических фактов."""

from app.schemas import ProductInput
from app.validation import SEO_DESCRIPTION_MAX, SEO_DESCRIPTION_MIN
from app.variant_scope import VariantScope, variant_scope


def _editorial_category(product: ProductInput) -> str:
    """Classify by the declared type and product name, not inferred use."""
    identity = (f"{product.name} {product.specs.get('тип', '')}").casefold()

    if "манометр" in identity:
        return "pressure_gauge"

    if "термометр" in identity:
        return "thermometer"

    if "давлен" in identity and any(term in identity for term in ("преобразоват", "датчик")):
        return "pressure_transmitter"

    if any(
        term in identity
        for term in (
            "измерител",
            "регулятор",
            "контроллер",
            "счётчик",
            "счетчик",
            "индикатор",
        )
    ):
        return "controller"

    return "generic"


def _editorial_headings(
    category: str,
    extra_heading: str,
) -> tuple[str, str, str]:
    """Choose headings without changing classification of specs."""
    if category == "pressure_gauge":
        return (
            "Диапазоны и точность измерения",
            "Корпус, присоединение и размеры",
            extra_heading,
        )

    if category == "thermometer":
        return (
            "Измерительные показатели",
            "Монтаж, погружная часть и размеры",
            extra_heading,
        )

    if category == "pressure_transmitter":
        return (
            "Диапазоны и погрешности",
            "Присоединения и конструкция",
            extra_heading,
        )

    return (
        "Измерительные характеристики",
        "Габариты, монтаж и исполнения",
        extra_heading,
    )


def _editorial_selection(
    product: ProductInput,
    groups: list[list[tuple[str, str]]],
) -> str:
    """Select criteria that are actually present in source specs."""
    labels = {
        "pressure_gauge": "манометра",
        "thermometer": "термометра",
        "pressure_transmitter": "преобразователя давления",
        "controller": "измерительного прибора",
        "generic": "оборудования",
    }

    selected: list[str] = []

    for group in groups:
        for name, _ in group:
            if name.casefold() in {
                "тип",
                "серия",
                "статус исполнения",
            }:
                continue

            if name not in selected and len(name) <= 45:
                selected.append(name)
                break

        if len(selected) == 2:
            break

    if len(selected) < 2:
        for name in product.specs:
            if name not in selected and name.casefold() != "статус исполнения" and len(name) <= 45:
                selected.append(name)

            if len(selected) == 2:
                break

    kind = labels[_editorial_category(product)]

    if not selected:
        return f"При подборе {kind} сверяют приведённые технические характеристики."

    criteria = " и ".join(f"«{name}»" for name in selected[:2])

    return f"При подборе {kind} сверяют {criteria}."


def _editorial_conclusion(
    product: ProductInput,
    entries: list[tuple[str, str]],
    is_series: bool,
) -> str:
    """Ground the closing paragraph in variant labels and product type."""
    category = _editorial_category(product)

    if not is_series:
        endings = {
            "pressure_gauge": (
                "Перед заказом проверяют соответствие "
                "измерительных и присоединительных параметров "
                "конкретному артикулу по документации."
            ),
            "thermometer": (
                "Выбранное исполнение и параметры "
                "присоединения проверяют по документации "
                "на конкретный термометр."
            ),
            "pressure_transmitter": (
                "Перед заказом уточняют характеристики "
                "конкретного преобразователя по документации "
                "изготовителя."
            ),
            "controller": (
                "Перед заказом необходимо сверить "
                "характеристики конкретного исполнения "
                "с технической документацией."
            ),
            "generic": ("Параметры конкретного исполнения проверяют по технической документации."),
        }
        return endings[category]

    if variant_scope(product) == VariantScope.STATUS_ONLY:
        # The source only identifies a series without selecting an article.
        # No individual specification was marked as an alternative.
        return (
            "Карточка относится к серии без выбранного артикула. "
            "Характеристики конкретного исполнения проверяют "
            "по документации изготовителя."
        )

    variant_names = [
        name
        for name, value in entries
        if "варианты серии" in value.casefold() and "статус" not in name.casefold()
    ]

    if len(variant_names) >= 2:
        shown = variant_names[:2]
    else:
        shown = variant_names[:1]

    if shown and sum(len(name) for name in shown) <= 90:
        labels = " и ".join(f"«{name}»" for name in shown)
        opening = f"Для серии параметры {labels} перечислены по альтернативным исполнениям. "
    else:
        opening = "Для серии приведены характеристики альтернативных исполнений. "

    endings = {
        "pressure_gauge": (
            "Для заказа манометра подтверждают выбранное "
            "сочетание измерительных и присоединительных "
            "параметров по документации конкретного артикула."
        ),
        "thermometer": (
            "Выбирают конкретный артикул и сверяют "
            "диапазон, размеры и присоединение "
            "с документацией его исполнения."
        ),
        "pressure_transmitter": (
            "Наличие всех перечисленных вариантов в одном "
            "приборе не подтверждено; конкретную модификацию "
            "уточняют по документации изготовителя."
        ),
        "controller": (
            "Перечень не описывает одну готовую конфигурацию. "
            "Совместимость выбранных параметров "
            "проверяют по документации артикула."
        ),
        "generic": (
            "Эти значения не следует считать параметрами "
            "единого артикула; конкретную модификацию "
            "выбирают по документации."
        ),
    }

    return opening + endings[category]


"""V013-04E-F1: structured safe SEO layout. Production insertion candidate."""

_SECTIONS = (
    "measurement",
    "outputs",
    "mechanical",
    "electrical",
    "construction",
    "execution",
    "other",
)


def _seo_section(name: str) -> str:
    """Map SOURCE spec name to a reader-facing block; do not infer values."""
    n = name.casefold()
    if n == "статус исполнения":
        return "execution"
    # Order matters: connector terms precede electrical output terms.
    if any(
        t in n
        for t in (
            "присоедин",
            "штуцер",
            "резьб",
            "габарит",
            "диаметр",
            "расположение",
            "погружной части",
            "исполнения корпуса",
            "тип корпуса",
            "соединител",
        )
    ):
        return "mechanical"
    if any(
        t in n
        for t in (
            "питани",
            "потребляемая мощность",
            "встроенный источник",
            "ток встроенного источника",
        )
    ):
        return "electrical"
    if any(t in n for t in ("интерфейс", "протокол")):
        return "electrical"
    if any(t in n for t in ("выход", "реле", "коммутируемый ток", "сигнализац")):
        return "outputs"
    if any(t in n for t in ("материал", "защит", "температура", "гидрозаполнени")):
        return "construction"
    if n in {"тип", "серия", "единицы шкалы", "чувствительный элемент"} or any(
        t in n
        for t in (
            "диапазон",
            "предел",
            "погрешност",
            "класс точности",
            "вход",
            "датчик",
            "канал",
            "время опроса",
            "время измерения",
            "время измер",
            "минимальное время опроса",
            "перенастройка диапазона",
        )
    ):
        return "measurement"
    return "other"


def _seo_section_labels(category: str) -> dict[str, str]:
    measuring = {
        "pressure_gauge": "Диапазоны и точность измерения",
        "thermometer": "Измерительные показатели",
        "pressure_transmitter": "Диапазоны и погрешности",
    }.get(category, "Измерительные характеристики")
    mechanical = {
        "pressure_gauge": "Корпус, присоединение и размеры",
        "thermometer": "Монтаж, погружная часть и размеры",
        "pressure_transmitter": "Присоединения и конструкция",
    }.get(category, "Габариты, монтаж и исполнения")
    return {
        "measurement": measuring,
        "outputs": "Выходы и управление",
        "mechanical": mechanical,
        "electrical": "Электропитание, интерфейсы и дополнительные параметры",
        "construction": "Конструкция и материалы"
        if category in {"pressure_gauge", "thermometer"}
        else "Материалы, защита и условия",
        "execution": "Исполнение",
        "other": "Дополнительные характеристики",
    }


def _structured_seo_fallback(product, entries) -> str | None:
    """Full semantic grouping followed by lean source-preserving variants."""
    category = _editorial_category(product)
    # Preserve the original source-aware expansion for terse thermometer inputs.
    if category == "thermometer" and len(product.description or "") < 85:
        return None
    groups = {key: [] for key in _SECTIONS}
    for name, value in entries:
        groups[_seo_section(name)].append((name, value))
    # Avoid accidentally pairing IP protection with the material of a sleeve.
    # IP is a property of the named housing, not of a nearby protective sleeve.
    # Place casing protection before sleeve materials. Keep every source pair intact.
    groups["construction"].sort(
        key=lambda pair: (
            0 if "степен" in pair[0].casefold() and "защит" in pair[0].casefold() else 1
        )
    )

    labels = _seo_section_labels(category)
    introduction = (
        product.name
        if product.manufacturer.casefold() in product.name.casefold()
        else f"{product.name} ({product.manufacturer})"
    )
    purpose = (product.description or "").strip().split(". ", 1)[0].strip(" .")
    intro = f"{introduction}." + (f" {purpose}." if purpose and len(purpose) <= 220 else "")
    # Do not claim all options are present in a specific device.
    series = any("варианты серии" in v.casefold() for _, v in entries)
    sections = [
        f"{labels[key]}: " + "; ".join(f"{name} — {value}" for name, value in groups[key]) + "."
        for key in _SECTIONS
        if groups[key]
    ]
    short_end = (
        "Перед заказом уточняют исполнение по документации."
        if series
        else "Параметры конкретного изделия сверяют по документации."
    )
    full_end = _editorial_conclusion(product, entries, series)
    # Prefer a real introduction and concrete sections; eliminate editorial
    # filler first if the source is dense, without deleting specification pairs.
    selection_groups = [groups["measurement"], groups["mechanical"], groups["construction"]]
    selection = _editorial_selection(product, selection_groups)
    attempts = [
        [f"{intro} {selection}", *sections, full_end],
        [f"{intro} {selection}", *sections, short_end],
        [intro, *sections, full_end],
        [intro, *sections, short_end],
        [intro, *sections],
    ]
    for parts in attempts:
        text = "\n\n".join(parts)
        if SEO_DESCRIPTION_MIN <= len(text) <= SEO_DESCRIPTION_MAX:
            return text
    return None


def grounded_seo_description(product: ProductInput) -> str | None:
    """Собрать текст только при достаточной полноте исходных параметров."""
    if any(not value.strip() for value in product.specs.values()):
        return None

    entries = [(key, value.strip()) for key, value in product.specs.items()]
    if len(entries) < 8:
        return None

    # V013-04E-F1: semantic sectioning before legacy fallback.
    structured = _structured_seo_fallback(product, entries)
    if structured is not None:
        return structured

    groups: list[list[tuple[str, str]]] = [[], [], []]
    for name, value in entries:
        normalized = name.casefold()

        # Типы выходных устройств не относятся к измерительным режимам.
        if normalized in {"тип", "серия"} or any(
            term in normalized
            for term in (
                "диапазон",
                "верхние пределы",
                "класс точности",
                "единицы шкалы",
                "чувствительный элемент",
                "погрешност",
                "время опроса",
                "время измерения",
                "количество измерительных",
                "количество универсальных входов",
                "количество универсальных измерительных входов",
                "количество каналов",
                "входные сигналы",
            )
        ):
            groups[0].append((name, value))
        elif any(
            term in normalized
            for term in (
                "диаметр",
                "расположение",
                "резьба",
                "присоединение",
                "длина погружной",
                "габариты",
                "исполнения корпуса",
            )
        ):
            groups[1].append((name, value))
        else:
            groups[2].append((name, value))

    # Ставим степень защиты до материалов, чтобы не создавать
    # ошибочную связь IP с защитной гильзой.
    groups[2].sort(
        key=lambda item: (
            0 if "степен" in item[0].casefold() and "защит" in item[0].casefold() else 1
        )
    )

    introduction = (
        product.name
        if product.manufacturer.casefold() in product.name.casefold()
        else f"{product.name} ({product.manufacturer})"
    )
    purpose = (product.description or "").strip().split(". ", 1)[0].strip(" .")
    intro = f"{introduction}. "
    if purpose and len(purpose) <= 220:
        intro += f"{purpose}. "
    intro += _editorial_selection(product, groups)
    paragraphs = [intro]

    # Не называем параметры механического манометра электрическими.
    extra_names = " ".join(name.casefold() for name, _ in groups[2])
    electrical = any(
        term in extra_names
        for term in ("питание", "напряжение", "частота", "интерфейс", "протокол")
    )
    extra_heading = (
        "Электропитание, интерфейсы и дополнительные параметры"
        if electrical
        else "Конструкция и материалы"
    )

    headings = _editorial_headings(
        _editorial_category(product),
        extra_heading,
    )

    for heading, group in zip(headings, groups, strict=True):
        if not group:
            continue
        details = "; ".join(f"{name} — {value}" for name, value in group)
        paragraphs.append(f"{heading}: {details}.")

    is_series = any("варианты серии" in value.casefold() for _, value in entries)

    paragraphs.append(_editorial_conclusion(product, entries, is_series))

    description = "\n\n".join(paragraphs)

    # A short but sufficiently specified thermometer may need
    # one more source-grounded paragraph. Do not pad other products.
    if (
        len(description) < SEO_DESCRIPTION_MIN
        and not is_series
        and _editorial_category(product) == "thermometer"
    ):
        criteria = [
            name
            for name in (
                "диапазон показаний",
                "присоединение",
                "длина погружной части",
            )
            if name in product.specs
        ]
        materials = [
            name
            for name in (
                "материал корпуса",
                "материал штока",
                "материал защитной гильзы",
            )
            if name in product.specs
        ]

        if len(criteria) >= 2 and len(materials) >= 2:
            criteria_text = ", ".join(f"«{name}»" for name in criteria)
            materials_text = ", ".join(f"«{name}»" for name in materials)
            additional = (
                "При выборе артикула отдельно сопоставляют "
                f"параметры {criteria_text}. "
                "Материалы указаны для разных элементов "
                f"прибора: {materials_text}. "
                "Эти сведения не подтверждают "
                "совместимость конкретного исполнения "
                "с условиями установки; её проверяют "
                "по документации изготовителя."
            )

            expanded = paragraphs.copy()
            expanded.insert(-1, additional)
            expanded_description = "\n\n".join(expanded)

            if SEO_DESCRIPTION_MIN <= len(expanded_description) <= SEO_DESCRIPTION_MAX:
                return expanded_description

    if SEO_DESCRIPTION_MIN <= len(description) <= SEO_DESCRIPTION_MAX:
        return description

    # Если превышен лимит, сокращаем редакторские пояснения,
    # но сохраняем исходные технические характеристики.
    if len(description) > SEO_DESCRIPTION_MAX:
        shorter = paragraphs.copy()

        if is_series and variant_scope(product) == VariantScope.STATUS_ONLY:
            shorter[-1] = (
                "Карточка относится к серии без выбранного артикула. "
                "Параметры исполнения уточняют по технической документации."
            )
        elif is_series:
            shorter[-1] = (
                "Параметры с пометкой «варианты серии» относятся "
                "к разным исполнениям. Конкретную модификацию "
                "необходимо выбрать по технической документации."
            )
        else:
            shorter[-1] = (
                "Перед заказом следует проверить параметры "
                "конкретного исполнения по технической документации."
            )

        shorter_description = "\n\n".join(shorter)

        if SEO_DESCRIPTION_MIN <= len(shorter_description) <= SEO_DESCRIPTION_MAX:
            return shorter_description

        # Для особенно насыщенных источников пробуем компактную
        # запись без удаления названий и значений характеристик.
        compact = [f"{introduction}."]

        if purpose and len(purpose) <= 220:
            compact[0] += f" {purpose}."

        facts = "; ".join(f"{name} — {value}" for name, value in entries)
        compact.append(f"Характеристики: {facts}.")

        if is_series and variant_scope(product) == VariantScope.STATUS_ONLY:
            compact.append(
                "Серия представлена без выбранного артикула; его параметры "
                "уточняют по документации."
            )
        elif is_series:
            compact.append(
                "Указаны варианты серии. Перед заказом необходимо "
                "выбрать конкретную модификацию по документации."
            )
        else:
            compact.append("Перед заказом необходимо проверить параметры конкретного исполнения.")

        compact_description = "\n\n".join(compact)

        if SEO_DESCRIPTION_MIN <= len(compact_description) <= SEO_DESCRIPTION_MAX:
            return compact_description

    return None
