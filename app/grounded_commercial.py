"""Коммерческое пояснение только из предоставленных сведений о товаре."""

import re

from app.schemas import ProductInput


def _source_purpose(description: str | None) -> str | None:
    """Извлечь прямо указанную задачу измерения без её расширения."""
    if not description:
        return None

    for sentence in re.split(r"(?<=[.!?])\s+", description.strip()):
        match = re.search(r"\bдля измерения\b", sentence, flags=re.IGNORECASE)
        if match is None:
            continue

        preceding = sentence[: match.start()].casefold()
        if "не предназначен" in preceding or "не используется" in preceding:
            continue

        purpose = sentence[match.start() :].strip(" .")
        if 10 <= len(purpose) <= 220:
            return purpose

    return None


def grounded_commercial_note(
    product: ProductInput,
    selection_names: list[str],
) -> str:
    """Назначение, критерии закупки и ограничения без новых технических фактов."""
    purpose = _source_purpose(product.description)

    if purpose:
        opening = (
            "Для специалистов по закупке и подбору оборудования: "
            f"«{product.name}» предназначен {purpose}."
        )
    else:
        opening = (
            "Для специалистов по закупке и подбору оборудования: "
            f"«{product.name}» следует рассматривать по указанным "
            "исходным характеристикам."
        )

    relevant = list(
        dict.fromkeys(
            name
            for name in selection_names
            if name in product.specs and product.specs[name].strip()
        )
    )[:3]

    if relevant:
        criteria = f"При подборе следует сопоставить с заявкой параметры: {', '.join(relevant)}."
    else:
        criteria = "При подборе следует сопоставить исходные характеристики с требованиями заявки."

    is_series = any("варианты серии" in value.casefold() for value in product.specs.values())

    if is_series:
        description = (product.description or "").casefold()
        limit_unselected = "предел измерения" in description and any(
            marker in description for marker in ("не выбра", "не указан", "не задан")
        )

        if limit_unselected:
            conclusion = (
                "Для серии необходимо уточнить конкретное исполнение "
                "и предел измерения по технической документации."
            )
        else:
            conclusion = (
                "Для серии необходимо уточнить конкретное исполнение по технической документации."
            )
    else:
        conclusion = "Перед заказом следует проверить исполнение по технической документации."

    return " ".join((opening, criteria, conclusion))
