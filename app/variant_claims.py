"""Conservative checks for variant-specific technical claims."""

import re

from app.schemas import ProductCard, ProductInput

_RS485 = re.compile(r"RS[\s\-–—]*485", re.IGNORECASE)
_HART = re.compile(r"\bHART\b", re.IGNORECASE)
_ANALOG = re.compile(r"4\s*(?:…|–|-|\.{2,3})\s*20\s*мА", re.IGNORECASE)
_OPTIONAL = re.compile(
    r"зависит\s+от\s+(?:исполнения|модификации)"
    r"|в\s+зависимости\s+от\s+(?:исполнения|модификации)"
    r"|в\s+(?:отдельных|некоторых)\s+исполнениях"
    r"|опционал\w*|вариант\w*\s+серии",
    re.IGNORECASE,
)
_UNQUALIFIED_INTERFACE_PAIR = re.compile(r"\bHART\b\s+и\s+RS[\s\-–—]*485\b", re.IGNORECASE)

_SIMULTANEOUS = re.compile(
    r"одновременн\w*|оба\s+интерфейса"
    r"|в\s+одной\s+(?:модификации|конфигурации|исполнении)",
    re.IGNORECASE,
)
_NEGATED_SIMULTANEOUS = re.compile(
    r"\bне\b[^.!?;\n]{0,35}одновременн\w*",
    re.IGNORECASE,
)
_ANALOG_LABEL = re.compile(r"\bаналогов\w*\s+выход\w*", re.IGNORECASE)
_GRADE = re.compile(r"\b(?:SS\d{3,5}L?|ADC\d{2,4})\b", re.IGNORECASE)


def _sentences(card: ProductCard) -> list[str]:
    fields = [
        card.seo_title or "",
        card.seo_description or "",
        *card.search_queries,
        card.commercial_note or "",
    ]
    return [
        part.strip() for field in fields for part in re.split(r"[.!?;\n]+", field) if part.strip()
    ]


def _material_mismatch(
    specs: dict[str, str],
    sentences: list[str],
) -> bool:
    membrane = _GRADE.search(specs.get("материал мембраны", ""))
    casing = _GRADE.search(specs.get("материал корпуса", ""))

    if not membrane or not casing:
        return False

    membrane_grade = membrane.group().casefold()
    casing_grade = casing.group().casefold()

    if membrane_grade == casing_grade:
        return False

    for sentence in sentences:
        for part, own, other in (
            ("мембран", membrane_grade, casing_grade),
            ("корпус", casing_grade, membrane_grade),
        ):
            pattern = re.compile(
                rf"\b(?:материал\s+)?{part}\w*\s*"
                r"(?:—|:|-|из|изготовлен\w*\s+из|выполнен\w*\s+из)\s*",
                re.IGNORECASE,
            )

            for match in pattern.finditer(sentence):
                tail = sentence[match.end() :][:100]
                fragment = re.split(
                    r"\b(?:корпус\w*|мембран\w*)\b|[,;.!?\n]",
                    tail,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].casefold()

                if other in fragment and own not in fragment:
                    return True

    return False


def variant_claim_warnings(
    product: ProductInput,
    card: ProductCard,
) -> list[str]:
    """Flag only explicit variant-compatibility contradictions."""
    warnings: list[str] = []
    specs = product.specs
    sentences = _sentences(card)

    interface_options = any(
        "интерфейс" in key.casefold()
        and "/" in value
        and "варианты серии" in value.casefold()
        and _HART.search(value)
        and _RS485.search(value)
        for key, value in specs.items()
    )

    if interface_options and any(
        _HART.search(sentence)
        and _RS485.search(sentence)
        and (
            _SIMULTANEOUS.search(sentence)
            or (_UNQUALIFIED_INTERFACE_PAIR.search(sentence) and not _OPTIONAL.search(sentence))
        )
        and not _NEGATED_SIMULTANEOUS.search(sentence)
        for sentence in sentences
    ):
        warnings.append(
            "Альтернативные интерфейсы HART и RS-485 ошибочно объединены в одну модификацию"
        )

    mounting_options = any(
        "исполнен" in key.casefold()
        and "настенн" in value.casefold()
        and "DIN" in value.upper()
        and "варианты серии" in value.casefold()
        for key, value in specs.items()
    )

    if mounting_options and any(
        re.search(r"настенн\w*", sentence, re.IGNORECASE)
        and re.search(r"\bDIN\b", sentence, re.IGNORECASE)
        and _SIMULTANEOUS.search(sentence)
        and not _NEGATED_SIMULTANEOUS.search(sentence)
        for sentence in sentences
    ):
        warnings.append("Альтернативные варианты монтажа объединены в одну модификацию")

    optional_analog = any(
        "аналогов" in key.casefold()
        and _ANALOG.search(value)
        and ("зависит от исполнения" in value.casefold() or "опционал" in value.casefold())
        for key, value in specs.items()
    )

    if optional_analog and any(
        _ANALOG_LABEL.search(sentence)
        and _ANALOG.search(sentence)
        and not _OPTIONAL.search(sentence)
        for sentence in sentences
    ):
        warnings.append("Аналоговый выход 4–20 мА указан без ограничения по исполнению")

    if _material_mismatch(specs, sentences):
        warnings.append("Материал одного узла ошибочно приписан другому")

    return warnings
