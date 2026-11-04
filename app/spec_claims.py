"""Консервативная проверка числовых утверждений о характеристиках.

Поддерживаются явные связки: диапазон, диаметр, класс точности и резьба.
Это дополнительный фильтр, а не полноценная семантическая экспертиза.
"""

import re

from app.schemas import ProductInput

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_UNIT = re.compile(
    r"(?<!\w)(?:МПа|MPa|кПа|kPa|Па|Pa|бар|bar|мм|см|°[ \t]*[CС])\b",
    re.IGNORECASE,
)
_THREAD_VALUE = re.compile(
    r"\b(?:G[ \t]*\d+(?:/\d+)?|M[ \t]*\d+(?:[xх×]\d+(?:[.,]\d+)?)?)\b",
    re.IGNORECASE,
)

_RANGE_CLAIM = re.compile(
    r"\b(?:диапазон(?:а|е|у|ом)?"
    r"(?:[ \t]+(?:измерени[йя]|показани[йя]|давления|температуры)"
    r"(?:[ \t]+давления)?)?"
    r"|предел(?:[ \t]+измерени[йя])?)"
    r"[ \t]*(?:[:=—–-][ \t]*)?(?:от[ \t]+)?"
    r"(?P<first>\+?\d+(?:[.,]\d+)?)"
    r"(?:[ \t]*(?:[-–—…]|\.\.{2,3}|до)"
    r"[ \t]*\+?(?P<second>\d+(?:[.,]\d+)?))?"
    r"[ \t]*(?P<unit>МПа|MPa|кПа|kPa|Па|Pa|бар|bar|°[ \t]*[CС])\b",
    re.IGNORECASE,
)

_DIAMETER_CLAIM = re.compile(
    r"\bдиаметр(?:[ \t]+(?P<qualifier>корпуса|гильзы|штуцера|штока))?"
    r"[ \t]*(?:[:=—–-][ \t]*)?"
    r"(?P<number>\d+(?:[.,]\d+)?)"
    r"[ \t]*(?P<unit>мм|см)\b",
    re.IGNORECASE,
)

_ACCURACY_CLAIM = re.compile(
    r"\bкласс(?:[ \t]+точности)"
    r"[ \t]*(?:[:=—–-][ \t]*)?"
    r"(?P<number>\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)

_THREAD_CLAIM = re.compile(
    r"\bрезьба(?:[ \t]+(?P<qualifier>гильзы|штуцера))?"
    r"[ \t]*(?:[:=—–-][ \t]*)?"
    r"(?P<code>(?:G[ \t]*\d+(?:/\d+)?"
    r"|M[ \t]*\d+(?:[xх×]\d+(?:[.,]\d+)?)?))\b",
    re.IGNORECASE,
)

_QUALIFIER_STEMS = {
    "корпуса": "корпус",
    "гильзы": "гильз",
    "штуцера": "штуцер",
    "штока": "шток",
}

_MESSAGES = {
    "range": "Значение диапазона не соответствует исходной характеристике",
    "diameter": "Значение диаметра не соответствует исходной характеристике",
    "accuracy": "Класс точности не соответствует исходной характеристике",
    "thread": "Обозначение резьбы не соответствует исходной характеристике",
}


def _number(value: str) -> str:
    return value.replace(",", ".").lstrip("+")


def _unit(value: str) -> str:
    normalized = re.sub(r"[ \t]+", "", value.casefold())
    aliases = {
        "mpa": "мпа",
        "kpa": "кпа",
        "pa": "па",
        "bar": "бар",
        "°c": "°с",
    }
    return aliases.get(normalized, normalized)


def _code(value: str) -> str:
    return (
        re.sub(r"[ \t]+", "", value)
        .casefold()
        .replace("х", "x")
        .replace("×", "x")
        .replace(",", ".")
    )


def _source_values(
    product: ProductInput,
    kind: str,
    qualifier: str = "",
) -> list[str]:
    values = []

    for name, value in product.specs.items():
        key = name.casefold()

        if not value.strip():
            continue

        if kind == "range":
            matches = "диапазон" in key or ("предел" in key and "измерен" in key)
        elif kind == "diameter":
            matches = "диаметр" in key
        elif kind == "accuracy":
            matches = "класс точности" in key
        elif kind == "thread":
            matches = "резьба" in key
        else:
            matches = False

        if not matches:
            continue

        if qualifier:
            stem = _QUALIFIER_STEMS[qualifier.casefold()]
            if stem not in key:
                continue

        values.append(value)

    return values


def _numeric_supported(
    product: ProductInput,
    kind: str,
    numbers: tuple[str, ...],
    unit: str | None,
    qualifier: str = "",
) -> bool:
    wanted_numbers = {_number(value) for value in numbers}
    wanted_unit = _unit(unit) if unit is not None else None

    for value in _source_values(product, kind, qualifier):
        available_numbers = {_number(item) for item in _NUMBER.findall(value)}
        available_units = {_unit(item) for item in _UNIT.findall(value)}

        if not wanted_numbers.issubset(available_numbers):
            continue

        if wanted_unit is not None and wanted_unit not in available_units:
            continue

        return True

    return False


def specification_claim_warnings(product: ProductInput, text: str) -> list[str]:
    """Проверить явные утверждения по соответствующим полям specs."""
    warnings = []

    def report(kind: str) -> None:
        message = _MESSAGES[kind]
        if message not in warnings:
            warnings.append(message)

    for match in _RANGE_CLAIM.finditer(text):
        values = (match.group("first"),)
        if match.group("second"):
            values += (match.group("second"),)

        if not _numeric_supported(product, "range", values, match.group("unit")):
            report("range")

    for match in _DIAMETER_CLAIM.finditer(text):
        if not _numeric_supported(
            product,
            "diameter",
            (match.group("number"),),
            match.group("unit"),
            match.group("qualifier") or "",
        ):
            report("diameter")

    for match in _ACCURACY_CLAIM.finditer(text):
        if not _numeric_supported(
            product,
            "accuracy",
            (match.group("number"),),
            None,
        ):
            report("accuracy")

    for match in _THREAD_CLAIM.finditer(text):
        expected = _code(match.group("code"))
        sources = _source_values(product, "thread", match.group("qualifier") or "")

        if not any(
            expected in {_code(item) for item in _THREAD_VALUE.findall(source)}
            for source in sources
        ):
            report("thread")

    return warnings
