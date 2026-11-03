"""Воспроизводимое испытание 24 полностью синтетических товаров."""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.generator import generate_card
from app.schemas import GenerationStatus, ProductInput


@dataclass(frozen=True)
class Scenario:
    case_id: str
    group: str
    payload: dict
    response: str
    expected: GenerationStatus


class FakeProvider:
    """Подменяет GigaChat: сетевых запросов нет."""

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        if self.calls > 2:
            raise AssertionError("Превышен лимит обращений к модели")
        return self.response


def product(name: str, specs: dict, description: str | None) -> dict:
    return {
        "name": name,
        "manufacturer": "Вымышленный завод",
        "specs": specs,
        "description": description,
    }


def draft(payload: dict, *, note: str = "Для сравнения параметров.") -> str:
    name = payload["name"]
    return json.dumps(
        {
            "seo_title": name,
            "seo_description": f"{name}: краткое описание.",
            "search_queries": [
                name,
                f"{name} характеристики",
                f"{name} параметры",
            ],
            "commercial_note": note,
        },
        ensure_ascii=False,
    )


def pressure_specs() -> dict:
    return {
        "тип": "общетехнический манометр",
        "диаметр корпуса": "50 / 63 / 100 / 160 мм, варианты серии",
        "расположение штуцера": "радиальное / осевое, варианты серии",
        "резьба штуцера": "G1/2 / G1/4 / M12x1,5 / M20x1,5, варианты серии",
        "класс точности": "1,5 / 2,5, варианты серии",
        "материал корпуса": "сталь",
        "материал штуцера": "латунь",
        "материал защитного стекла": "пластик / приборное стекло, варианты серии",
        "степень защиты": "IP43",
        "возможность гидрозаполнения": "нет",
        "единицы шкалы": "МПа / кгс/см² / bar",
    }


def temperature_specs() -> dict:
    return {
        "тип": "биметаллический термометр",
        "серия": "ТЕСТ",
        "диаметр корпуса": "100 мм",
        "диапазон показаний": "0…+100 °C",
        "присоединение": "осевое",
        "резьба гильзы": "G1/2",
        "длина погружной части": "100 мм",
        "класс точности": "1,5",
        "материал корпуса": "коррозионностойкая сталь",
        "материал штока": "нержавеющая сталь",
        "материал защитной гильзы": "латунь",
        "чувствительный элемент": "биметаллическая спираль",
        "степень защиты корпуса": "IP54",
    }


def pressure_variant(index: int) -> dict:
    """Пять разных полностью вымышленных конфигураций манометров."""
    changes = {
        1: {"диаметр корпуса": "80 / 100 / 150 мм, варианты серии"},
        2: {"класс точности": "1,0 / 1,5, варианты серии"},
        3: {"резьба штуцера": "G1/8 / G3/8, варианты серии"},
        4: {"материал корпуса": "алюминий"},
        5: {"степень защиты": "IP44"},
    }
    specs = pressure_specs()
    specs.update(changes[index])
    return specs


def temperature_variant(index: int) -> dict:
    """Пять разных полностью вымышленных конфигураций термометров."""
    changes = {
        1: {"диапазон показаний": "-20…+80 °C"},
        2: {"диаметр корпуса": "63 мм"},
        3: {"резьба гильзы": "M20x1,5"},
        4: {"материал защитной гильзы": "нержавеющая сталь"},
        5: {"степень защиты корпуса": "IP53"},
    }
    specs = temperature_specs()
    specs.update(changes[index])
    return specs


def build_cases() -> list[Scenario]:
    cases = []

    # 10 подробных карточек: корректный гибридный результат.
    for index in range(1, 6):
        meter = product(
            f"Манометр ТЕСТ-М{index:02d} (серия)",
            pressure_variant(index),
            "Демонстрационный манометр для измерения давления "
            "на условном стенде. Значения вымышлены.",
        )
        cases.append(
            Scenario(
                f"rich-meter-{index:02d}",
                "rich",
                meter,
                draft(meter, note="Гарантия 25 лет."),
                GenerationStatus.READY_FOR_REVIEW,
            )
        )

        thermometer = product(
            f"Термометр ТЕСТ-Т{index:02d}",
            temperature_variant(index),
            "Демонстрационный термометр для измерения температуры "
            "на условном стенде. Значения вымышлены.",
        )
        cases.append(
            Scenario(
                f"rich-thermometer-{index:02d}",
                "rich",
                thermometer,
                draft(thermometer, note="Гарантия 25 лет."),
                GenerationStatus.READY_FOR_REVIEW,
            )
        )

    # 6 неполных карточек: нельзя добивать SEO вымыслом.
    sparse_names = (
        "Барометр Б-ДЕМО",
        "Расходомер Р-ДЕМО",
        "Уровнемер У-ДЕМО",
        "Датчик давления Д-ДЕМО",
        "Регулятор РГ-ДЕМО",
        "Индикатор И-ДЕМО",
    )
    for index, name in enumerate(sparse_names, start=1):
        specs = {
            "тип": "демонстрационный прибор",
            "диапазон": "условный диапазон",
            "исполнение": "не уточнено",
            "подключение": "не уточнено",
        }
        specs = dict(list(specs.items())[: 1 + index % 4])
        item = product(
            name,
            specs,
            "Учебный пример без полного технического паспорта.",
        )
        cases.append(
            Scenario(
                f"sparse-{index:02d}",
                "sparse",
                item,
                draft(item),
                GenerationStatus.REQUIRES_REVISION,
            )
        )

    # 2 случая полного отсутствия технических сведений.
    for index, specs in enumerate(({}, {"диапазон": ""}), start=1):
        item = product(f"Прибор БЕЗ-ДАННЫХ-{index}", specs, None)
        cases.append(
            Scenario(
                f"empty-{index:02d}",
                "empty",
                item,
                draft(item),
                GenerationStatus.INSUFFICIENT_DATA,
            )
        )

    # 2 случая пропущенного значения среди подробных характеристик.
    for index, original in enumerate((pressure_specs(), temperature_specs()), start=1):
        specs = dict(original)
        specs["материал корпуса"] = ""
        item = product(
            f"Прибор С-ПРОПУСКОМ-{index}",
            specs,
            "Учебный пример с незаполненным техническим полем.",
        )
        cases.append(
            Scenario(
                f"blank-{index:02d}",
                "blank",
                item,
                draft(item),
                GenerationStatus.REQUIRES_REVISION,
            )
        )

    # 2 неподтверждённых рекламных обещания в ответе модели.
    for index, note in enumerate(
        ("Гарантия 25 лет.", "Высокая точность измерений."),
        start=1,
    ):
        item = product(
            f"Прибор РИСК-{index}",
            {"тип": "измерительный прибор", "корпус": "металл"},
            "Демонстрационный прибор.",
        )
        cases.append(
            Scenario(
                f"unsafe-{index:02d}",
                "unsafe",
                item,
                draft(item, note=note),
                GenerationStatus.REQUIRES_REVISION,
            )
        )

    # 2 повреждённых JSON-ответа LLM.
    for index, response in enumerate(
        ("not-json", '{"seo_title": "Оборванный ответ",'),
        start=1,
    ):
        item = product(
            f"Прибор JSON-ОШИБКА-{index}",
            {"тип": "измерительный прибор"},
            "Демонстрационный прибор.",
        )
        cases.append(
            Scenario(
                f"invalid-{index:02d}",
                "invalid",
                item,
                response,
                GenerationStatus.REQUIRES_REVISION,
            )
        )

    assert len(cases) == 24
    assert len({case.case_id for case in cases}) == 24
    return cases


def run_case(case: Scenario) -> dict:
    source = ProductInput.model_validate(case.payload)
    provider = FakeProvider(case.response)
    result = generate_card(source, provider)  # type: ignore[arg-type]

    card = result.card
    seo = (card.seo_description or "").strip()
    title = (card.seo_title or "").strip()
    commercial = (card.commercial_note or "").strip()
    problems = []

    if result.status != case.expected:
        problems.append("Неверный итоговый статус")

    if card.specifications != source.specs:
        problems.append("Изменены исходные характеристики")

    if provider.calls > 2:
        problems.append("Превышен лимит вызовов модели")

    if case.group == "rich":
        if not 800 <= len(seo) <= 1200:
            problems.append("Не соблюдена длина SEO")
        if not 0 < len(title) <= 70:
            problems.append("Не соблюдена длина заголовка")
        if not 3 <= len(card.search_queries) <= 5:
            problems.append("Неверное число поисковых запросов")
        if not commercial:
            problems.append("Пустой коммерческий блок")
        if result.warnings or result.missing_fields:
            problems.append("Предупреждения в подробном сценарии")
        if "Гарантия 25 лет" in seo + commercial:
            problems.append("Небезопасный текст модели попал в результат")
        if provider.calls != 2:
            problems.append("Ожидалось два обращения к тестовой модели")

    if case.group == "empty":
        if provider.calls != 0:
            problems.append("При отсутствии данных модель не должна вызываться")
        if not result.missing_fields:
            problems.append("Не обозначены отсутствующие сведения")

    if case.group == "blank" and not result.missing_fields:
        problems.append("Не отмечен незаполненный параметр")

    if case.group == "unsafe" and not any(
        "гарант" in warning.casefold() or "преимущества" in warning.casefold()
        for warning in result.warnings
    ):
        problems.append("Не обнаружено неподтверждённое утверждение")

    if case.group == "invalid" and not any(
        "некоррект" in warning.casefold() for warning in result.warnings
    ):
        problems.append("Не обнаружен повреждённый ответ LLM")

    if case.group in ("sparse", "blank", "unsafe", "invalid"):
        if result.status == GenerationStatus.READY_FOR_REVIEW:
            problems.append("Негативный сценарий ошибочно принят")

    return {
        "case_id": case.case_id,
        "group": case.group,
        "source_kind": "fully_synthetic",
        "llm_kind": "offline_fake_provider",
        "expected_status": case.expected.value,
        "actual_status": result.status.value,
        "llm_calls": provider.calls,
        "seo_length": len(seo),
        "passed": not problems,
        "problems": problems,
        "input": source.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="24 синтетических сценария без обращений к GigaChat"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/stage11_synthetic_batch_24"),
    )
    args = parser.parse_args()

    output = args.output
    if output.exists():
        parser.error("Каталог отчёта уже существует; перезапись запрещена")

    results = [run_case(case) for case in build_cases()]
    summary = {
        "count": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "by_group": dict(sorted(Counter(item["group"] for item in results).items())),
        "by_status": dict(sorted(Counter(item["actual_status"] for item in results).items())),
        "note": (
            "Все товары вымышлены. Все ответы LLM подменены. "
            "Успешный отказ также считается PASS. "
            "Это не проверка качества реального GigaChat."
        ),
    }

    output.mkdir(parents=True, exist_ok=False)
    for record in results:
        target = output / f"{record['case_id']}.json"
        target.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=== SYNTHETIC BATCH ===")
    for record in results:
        print(
            f"{'PASS' if record['passed'] else 'FAIL'} "
            f"{record['case_id']}: "
            f"{record['actual_status']}, "
            f"SEO={record['seo_length']}, "
            f"calls={record['llm_calls']}"
        )
        for problem in record["problems"]:
            print("  PROBLEM:", problem)

    print()
    print("TOTAL:", summary["count"])
    print("PASS:", summary["passed"])
    print("FAIL:", summary["failed"])
    print("BY STATUS:", summary["by_status"])
    print("REPORT:", output / "summary.json")

    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
