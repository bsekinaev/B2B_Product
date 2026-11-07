"""LLM-06: preserve near-target drafts without accepting dangerous claims."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_queries import grounded_search_queries
from app.schemas import GenerationSource, GenerationStatus, ProductCard, ProductInput
from app.seo_completion import complete_short_seo
from app.validation import validate_generated_card

ROOT = Path(__file__).resolve().parents[1]


def load(identifier: str) -> ProductInput:
    manifest = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["items"] if item["id"] == identifier)
    return ProductInput.model_validate_json(
        (ROOT / entry["input_file"]).read_text(encoding="utf-8")
    )


class Provider:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls = 0

    def generate_text(self, **_kwargs: Any) -> str:
        self.calls += 1
        if not self.replies:
            raise AssertionError("Unexpected second or third LLM call")
        return self.replies.pop(0)


def answer(item: ProductInput, seo: str, note: str | None = None) -> str:
    return json.dumps(
        {
            "seo_title": item.name,
            "seo_description": seo,
            "search_queries": grounded_search_queries(item),
            "commercial_note": (
                grounded_commercial_note(item, list(item.specs)[:3]) if note is None else note
            ),
        },
        ensure_ascii=False,
    )


TRM_SEO = (
    "Двухканальный измеритель-регулятор ОВЕН ТРМ202 предназначен для обработки сигналов "
    "от датчиков и управления технологическими процессами. Устройство оснащено двумя "
    "измерительными каналами и двумя выходными устройствами, поддерживает входные "
    "сигналы термопреобразователей и унифицированных электрических сигналов. "
    "Питание — от 90 до 245 В переменного тока, частота сети — от 47 до 63 Гц. "
    "Время опроса измерительного входа не превышает 1 секунду. Интерфейс связи RS-485 "
    "позволяет интегрировать прибор в системы автоматизации. Погрешность измерений "
    "составляет ±0,5% с остальными измерительными сигналами и ±0,25% с "
    "термопреобразователями сопротивления. Потребляемая мощность устройства — "
    "не более 6 ВА. Подбор подходящего варианта требует уточнения модификации "
    "и комплектации серии."
)

ROSMA_SEO = (
    "Биметаллический термометр РОСМА БТ-51.211 предназначен для контроля температуры "
    "жидкости, пара и газа в системах отопления, водоснабжения, кондиционирования и "
    "вентиляции. Диапазон измерений: 0…+100 °C, класс точности — 1,5. "
    "Корпус изготовлен из коррозионностойкой стали, погружная часть — из нержавеющей "
    "стали, защитный элемент — латунная гильза длиной 100 мм. "
    "Присоединение осевое, резьба G1/2. Степень защиты IP54. "
    "Чувствительным элементом является биметаллическая спираль. "
    "Подбор устройства требует уточнения следующих параметров: минимальная и "
    "максимальная рабочая температура среды, давление, среда эксплуатации, "
    "дополнительные интерфейсы и протоколы передачи данных."
)


def test_near_target_real_trm_draft_is_completed_by_verified_source() -> None:
    item = load("owen_trm202")
    assert 650 <= len(TRM_SEO) < 800
    provider = Provider(answer(item, TRM_SEO))
    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert provider.calls == 1
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.LLM_GROUNDED
    assert "seo_grounded_completion" in result.generation_meta.reason_codes
    assert "fallback_selected" not in result.generation_meta.reason_codes
    assert result.card.seo_description.startswith(TRM_SEO)
    assert 800 <= len(result.card.seo_description or "") <= 1200
    assert result.card.specifications == item.specs
    assert not result.warnings


def test_real_rosma_sleeve_length_misattribution_is_blocking() -> None:
    item = load("rosma_bt_51_211")
    draft = ProductCard(
        seo_title=item.name,
        seo_description=ROSMA_SEO,
        search_queries=grounded_search_queries(item),
        commercial_note=grounded_commercial_note(item, list(item.specs)[:3]),
        specifications=dict(item.specs),
    )
    result = validate_generated_card(item, draft)
    assert any("Длина погружной части" in w for w in result.warnings)


def test_rosma_claim_cannot_be_automatically_completed() -> None:
    item = load("rosma_bt_51_211")
    # A second invalid revision must retain the established safe fallback.
    provider = Provider(answer(item, ROSMA_SEO), answer(item, ROSMA_SEO))
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert "seo_grounded_completion" not in result.generation_meta.reason_codes
    assert result.card.specifications == item.specs


def test_genuine_sleeve_length_source_allows_same_wording() -> None:
    item = load("rosma_bt_51_211")
    item = item.model_copy(update={"specs": {**item.specs, "длина защитной гильзы": "100 мм"}})
    result = validate_generated_card(
        item,
        ProductCard(
            seo_title=item.name,
            seo_description=ROSMA_SEO,
            search_queries=grounded_search_queries(item),
            commercial_note=grounded_commercial_note(item, list(item.specs)[:3]),
            specifications=dict(item.specs),
        ),
    )
    assert not any("Длина погружной части" in w for w in result.warnings)


def test_short_draft_or_sparse_specs_cannot_be_padded() -> None:
    item = load("owen_trm202")
    assert complete_short_seo(item, "Короткое описание.") is None
    sparse = item.model_copy(update={"specs": {"тип": "контроллер"}})
    assert complete_short_seo(sparse, TRM_SEO) is None


def test_unsafe_commercial_is_not_approved_by_completion() -> None:
    item = load("owen_trm202")
    provider = Provider(answer(item, TRM_SEO, "Гарантия 25 лет."), answer(item, TRM_SEO))
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source != GenerationSource.LLM_GROUNDED
    assert "seo_grounded_completion" not in result.generation_meta.reason_codes
    assert "гарант" not in (result.card.commercial_note or "").casefold()


def test_pd200_invalid_interfaces_are_not_completed() -> None:
    item = load("owen_pd200")
    bad = "Интеллектуальный преобразователь давления ОВЕН ПД200. " + (
        "Прибор оснащен интерфейсами HART и RS-485. " * 16
    )
    assert 650 <= len(bad) < 800
    initial = validate_generated_card(
        item,
        ProductCard(
            seo_title=item.name,
            seo_description=bad,
            search_queries=grounded_search_queries(item),
            commercial_note=grounded_commercial_note(item, list(item.specs)[:3]),
            specifications=dict(item.specs),
        ),
    )
    assert len(initial.warnings) >= 2
    provider = Provider(answer(item, bad), answer(item, bad))
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source != GenerationSource.LLM_GROUNDED


def test_legacy_sources_remain_unchanged() -> None:
    assert GenerationSource.INITIAL_LLM.value == "initial_llm"
    assert GenerationSource.REFINED_LLM.value == "refined_llm"
    assert GenerationSource.FALLBACK.value == "fallback"
    assert GenerationSource.LLM_GROUNDED.value == "llm_grounded"


def test_already_represented_facts_are_not_repeated() -> None:
    item = ProductInput(
        name="Прибор",
        manufacturer="Завод",
        specs={f"параметр {index}": "ABC" for index in range(8)},
        description="Техническая документация.",
    )
    source = ("Описание прибора, значение ABC приведено в исходных данных. " * 15)[:750]
    assert 650 <= len(source) < 800
    assert complete_short_seo(item, source) is None


def test_oversized_single_fact_is_never_appended_past_limit() -> None:
    item = ProductInput(
        name="Прибор",
        manufacturer="Завод",
        specs={f"параметр {index}": f"{index}" + "X" * 490 for index in range(8)},
        description="Техническая документация.",
    )
    source = ("Сведения о приборе и его применении. " * 22)[:750]
    assert 650 <= len(source) < 800
    assert complete_short_seo(item, source) is None


def test_completion_fails_closed_if_revalidation_rejects_candidate() -> None:
    item = load("owen_trm202")
    provider = Provider(answer(item, TRM_SEO), answer(item, TRM_SEO))
    # An intentionally poisoned completion demonstrates validation is mandatory.
    corrupted = TRM_SEO + " Гарантия 25 лет без подтверждающих документов."
    with patch("app.generator.complete_short_seo", return_value=corrupted):
        result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert "seo_grounded_completion_rejected" in result.generation_meta.reason_codes
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert "гарант" not in (result.card.seo_description or "").casefold()


def test_no_change_to_short_complete_text_when_absent_data() -> None:
    sparse = ProductInput(
        name="Термометр",
        manufacturer="Завод",
        specs={"тип": "термометр"},
    )
    assert complete_short_seo(sparse, "Измерение температуры. " * 35) is None
