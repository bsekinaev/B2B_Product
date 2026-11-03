"""Проверяемая сборка SEO из характеристик без новых технических фактов."""

from app.schemas import ProductInput
from app.validation import SEO_DESCRIPTION_MAX, SEO_DESCRIPTION_MIN


def grounded_seo_description(product: ProductInput) -> str | None:
    """Собрать текст только при достаточной полноте исходных параметров."""
    if any(not value.strip() for value in product.specs.values()):
        return None

    entries = [(key, value.strip()) for key, value in product.specs.items()]
    if len(entries) < 8:
        return None

    groups: list[list[tuple[str, str]]] = [[], [], []]
    for name, value in entries:
        normalized = name.casefold()

        if any(
            term in normalized
            for term in (
                "тип",
                "серия",
                "диапазон",
                "класс точности",
                "единицы шкалы",
                "чувствительный элемент",
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
    intro += "При подборе параметры прибора сверяют с требованиями точки установки."
    paragraphs = [intro]

    headings = (
        "Для оценки измерительных параметров указаны",
        "Для выбора размеров и присоединения приведены",
        "Конструктивные характеристики включают",
    )

    for heading, group in zip(headings, groups, strict=True):
        if not group:
            continue
        details = "; ".join(f"{name} — {value}" for name, value in group)
        paragraphs.append(f"{heading}: {details}.")

    is_series = any("варианты серии" in value.casefold() for _, value in entries)

    if is_series:
        paragraphs.append(
            "Значения с пометкой «варианты серии» относятся к "
            "альтернативным исполнениям, а не к одной готовой "
            "конфигурации. Перед заказом нужно выбрать требуемое "
            "сочетание параметров по документации на конкретный "
            "вариант. Окончательная модификация здесь не указана."
        )
    else:
        paragraphs.append(
            "При выборе прибора следует сопоставить измерительные "
            "параметры, габариты и способ присоединения с требованиями "
            "точки установки. Материалы элементов перечислены раздельно: "
            "сведения об одном узле нельзя переносить на другой. "
            "Перед заказом следует проверить исполнение "
            "по технической документации на конкретный артикул."
        )

    description = "\n\n".join(paragraphs)

    if not SEO_DESCRIPTION_MIN <= len(description) <= SEO_DESCRIPTION_MAX:
        return None

    return description
