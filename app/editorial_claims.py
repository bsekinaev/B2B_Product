"""Conservative editorial guards for model names and unsupported capabilities.

Only high-confidence patterns are blocking. This is not semantic fact-checking;
ready_for_review remains a human-review status, never automatic publication.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import ProductCard, ProductInput

_MODEL = re.compile(
    r"(?<!\w)(?P<prefix>[А-ЯA-Z]{3,8})-?(?P<digits>\d{3,6})(?!\w)",
    re.IGNORECASE,
)
_INDEPENDENT_PARAMETERS = re.compile(
    r"\b(?:двух|2)\s+независим\w*\s+"
    r"(?:технологическ\w*\s+)?(?:параметр\w*|контур\w*)",
    re.IGNORECASE,
)
_RS485 = re.compile(r"(?<!\w)RS[\s\-–—]*485(?!\w)", re.IGNORECASE)
_REMOTE = re.compile(r"\b(?:удал[её]н\w*|дистанционн\w*)\b", re.IGNORECASE)
_ACTION = re.compile(r"\b(?:мониторинг|управлен\w*|контрол\w*)\b", re.IGNORECASE)
_ENABLES = re.compile(
    r"\b(?:обеспечива\w*|позволя\w*|поддержива\w*|"
    r"предусматрива\w*|да[её]т)\b",
    re.IGNORECASE,
)
_DENIED = re.compile(
    r"\bне\s+(?:обеспечива\w*|позволя\w*|поддержива\w*|"
    r"предусматрива\w*|да[её]т)\b",
    re.IGNORECASE,
)


def _one_edit(a: str, b: str) -> bool:
    """True only for exactly one insertion, deletion, or replacement."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(left != right for left, right in zip(a, b, strict=True)) == 1
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def _model_query_mismatch(product: ProductInput, card: ProductCard) -> bool:
    """Catch likely single-character model-code typos, not arbitrary other codes."""
    expected = {
        (match.group("prefix").casefold(), match.group("digits"))
        for match in _MODEL.finditer(product.name)
    }
    if not expected:
        return False

    for query in card.search_queries:
        for match in _MODEL.finditer(query):
            prefix, digits = match.group("prefix").casefold(), match.group("digits")
            if (prefix, digits) in expected:
                continue
            if any(
                (digits == reference_digits and _one_edit(prefix, reference_prefix))
                or (prefix == reference_prefix and _one_edit(digits, reference_digits))
                for reference_prefix, reference_digits in expected
            ):
                return True
    return False


def _unsupported_independent_parameters(product: ProductInput, card: ProductCard) -> bool:
    text = "\n".join([card.seo_title or "", card.seo_description or "", card.commercial_note or ""])
    if not _INDEPENDENT_PARAMETERS.search(text):
        return False
    return not any(
        _INDEPENDENT_PARAMETERS.search(f"{name} {value}") for name, value in product.specs.items()
    )


def _unsupported_remote_rs485(product: ProductInput, card: ProductCard) -> bool:
    structured = [f"{name}: {value}" for name, value in product.specs.items()]
    if any(_REMOTE.search(entry) and _ACTION.search(entry) for entry in structured):
        return False

    fields = [
        card.seo_title or "",
        card.seo_description or "",
        *card.search_queries,
        card.commercial_note or "",
    ]
    for field in fields:
        for sentence in re.split(r"[.!?;\n]+", field):
            if (
                _RS485.search(sentence)
                and _REMOTE.search(sentence)
                and _ACTION.search(sentence)
                and _ENABLES.search(sentence)
                and not _DENIED.search(sentence)
            ):
                return True
    return False


def editorial_claim_warnings(product: ProductInput, card: ProductCard) -> list[str]:
    """Flag explicitly evidenced LLM-07 mistakes; do not mutate any card fields."""
    warnings: list[str] = []
    if _model_query_mismatch(product, card):
        warnings.append("В поисковых запросах указано ошибочное обозначение модели")
    if _unsupported_independent_parameters(product, card):
        warnings.append("Независимость двух параметров не подтверждена характеристиками")
    if _unsupported_remote_rs485(product, card):
        warnings.append("Удалённое управление через RS-485 не подтверждено характеристиками")
    return warnings
