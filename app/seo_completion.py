"""Conservative source-grounded completion for a near-target LLM SEO draft.

Never rewrites the model's words; contributes only documented source facts.
The caller MUST independently revalidate the entire resulting card.
"""

from app.schemas import ProductInput
from app.validation import SEO_DESCRIPTION_MAX, SEO_DESCRIPTION_MIN

MIN_PRESERVABLE_LENGTH = 650


def complete_short_seo(product: ProductInput, seo: str) -> str | None:
    """Extend a close-to-target draft with source facts; decline otherwise."""
    text = seo.strip()
    if not MIN_PRESERVABLE_LENGTH <= len(text) < SEO_DESCRIPTION_MIN:
        return None
    if sum(bool(value.strip()) for value in product.specs.values()) < 8:
        return None

    original = text.casefold()
    additions: list[str] = []

    status = product.specs.get("статус исполнения", "").strip()
    if "точная модификация не выбрана" in status.casefold():
        if "точная модификация не выбрана" not in original:
            additions.append("Исходные данные относятся к серии: точная модификация не выбрана.")

    # Add only value-bearing data. Do not invent product capabilities or standards.
    for name, value in product.specs.items():
        name, value = name.strip(), value.strip()
        if not name or not value or name.casefold() == "статус исполнения":
            continue
        if value.casefold() in original:
            continue
        additions.append(
            f"Для сопоставления исполнений учитывают параметр «{name}»: {value.rstrip('.')}."
        )

    result = text
    for addition in additions:
        candidate = result + " " + addition
        if len(candidate) > SEO_DESCRIPTION_MAX:
            continue
        result = candidate
        if len(result) >= SEO_DESCRIPTION_MIN:
            return result
    return None
