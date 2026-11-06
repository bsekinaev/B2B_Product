"""V013-04E-F1: тематическая группировка fallback без потери фактов."""

import json
from pathlib import Path

import pytest

from app.grounded_copy import grounded_seo_description
from app.schemas import ProductInput

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
ITEMS = MANIFEST["items"]


def load(identifier: str) -> ProductInput:
    item = next(row for row in ITEMS if row["id"] == identifier)
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


def section(description: str, heading: str) -> str:
    prefix = heading + ":"
    matches = [para for para in description.split("\n\n") if para.startswith(prefix)]
    assert len(matches) == 1, f"Section {heading!r} missing or duplicated"
    return matches[0]


@pytest.mark.parametrize("item", ITEMS, ids=[x["id"] for x in ITEMS])
def test_every_spec_remains_in_one_valid_description(item: dict) -> None:
    product = load(item["id"])
    original = dict(product.specs)
    description = grounded_seo_description(product)
    assert description is not None
    assert 800 <= len(description) <= 1200
    for name, value in original.items():
        fact = f"{name} — {value.strip()}"
        assert description.count(fact) == 1, (item["id"], name)
    assert product.specs == original


@pytest.mark.parametrize("identifier", ["owen_trm1", "owen_2trm1", "owen_trm10"])
def test_dense_controllers_have_separate_meaningful_sections(identifier: str) -> None:
    description = grounded_seo_description(load(identifier))
    assert description is not None
    assert "Характеристики:" not in description
    measured = section(description, "Измерительные характеристики")
    power = section(description, "Электропитание, интерфейсы и дополнительные параметры")
    outputs = section(description, "Выходы и управление")
    assert "время опроса измерительного входа" in measured
    assert "напряжение питания" in power
    assert "количество выходных устройств" in outputs
    assert "количество выходных устройств" not in power


def test_ukt38_relay_and_alarm_are_not_materials() -> None:
    description = grounded_seo_description(load("owen_ukt38"))
    assert description is not None
    outputs = section(description, "Выходы и управление")
    assert "коммутируемый ток реле — 4 А при 220 В" in outputs
    assert "сигнализация — авария объекта / авария датчика" in outputs
    assert "выходные устройства — электромагнитные реле" in outputs
    assert "Конструкция и материалы:" not in description
    assert "поддерживаемые датчики" in section(description, "Измерительные характеристики")


def test_rosma_ip54_is_explicitly_scoped_to_casing() -> None:
    product = load("rosma_bt_51_211")
    description = grounded_seo_description(product)
    assert description is not None

    construction = section(description, "Конструкция и материалы")
    casing = "степень защиты корпуса — IP54"
    sleeve = "материал защитной гильзы — латунь"
    assert casing in construction
    assert sleeve in construction
    assert construction.index(casing) < construction.index(sleeve)
    assert "гильзы — латунь; степень защиты корпуса — IP54" not in construction


def test_pd100_connectors_not_in_electrical_group() -> None:
    description = grounded_seo_description(load("owen_pd100_1x1"))
    assert description is not None
    mechanics = section(description, "Присоединения и конструкция")
    electrical = section(description, "Электропитание, интерфейсы и дополнительные параметры")
    assert "присоединительные штуцеры" in mechanics
    assert "выходной соединитель" in mechanics
    assert "присоединительные штуцеры" not in electrical


def test_pd200_materials_not_in_electrical_group() -> None:
    description = grounded_seo_description(load("owen_pd200"))
    assert description is not None
    materials = section(description, "Материалы, защита и условия")
    electrical = section(description, "Электропитание, интерфейсы и дополнительные параметры")
    measurement = section(description, "Диапазоны и погрешности")
    assert "материал мембраны" in materials
    assert "материал корпуса" in materials
    assert "материал мембраны" not in electrical
    assert "материал корпуса" not in electrical
    assert "верхние пределы избыточного давления" in measurement


def test_trm202_outputs_not_in_power() -> None:
    description = grounded_seo_description(load("owen_trm202"))
    assert description is not None
    assert "количество выходных устройств — 2" in section(description, "Выходы и управление")
    assert "количество выходных устройств" not in section(
        description, "Электропитание, интерфейсы и дополнительные параметры"
    )


def test_short_and_overfull_inputs_remain_conservative() -> None:
    sparse = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Завод",
        specs={"диапазон": "0–1 МПа", "класс точности": "1,5"},
        description="Для измерения давления.",
    )
    assert grounded_seo_description(sparse) is None
    oversized = ProductInput(
        name="Промышленный прибор",
        manufacturer="Завод",
        specs={f"параметр {i}": "значение " + "А" * 180 for i in range(10)},
        description="Тестовое оборудование.",
    )
    assert grounded_seo_description(oversized) is None
