"""LLM-08: regression guards for three defects captured in LLM-07, offline."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.editorial_claims import editorial_claim_warnings
from app.generator import generate_card
from app.grounded_queries import grounded_search_queries
from app.schemas import GenerationSource, GenerationStatus, ProductCard, ProductInput
from app.validation import validate_generated_card

ROOT = Path(__file__).resolve().parents[1]

SEO_LLM07 = (
    "Двухканальный измеритель-регулятор ОВЕН ТРМ202 предназначен для обработки "
    "сигналов от датчиков и управления технологическими процессами. Устройство "
    "оснащено двумя измерительными каналами и двумя выходными устройствами, "
    "поддерживает входные сигналы термопреобразователей и унифицированных "
    "электрических сигналов. Интерфейс RS-485 обеспечивает удалённый мониторинг "
    "и управление. Питание устройства — от 90 до 245 В переменного тока "
    "частотой 47–63 Гц. Погрешность измерений составляет ±0,5% с остальными "
    "сигналами и ±0,25% с термопреобразователями сопротивления. Время опроса "
    "измерительных входов не превышает 1 секунду, потребляемая мощность — "
    "не более 6 ВА. Подбор прибора требует уточнения модификации и условий эксплуатации."
)
QUERIES_LLM07 = [
    "двухканальный измеритель регулятор овен трдм202",
    "овен трм202 технические характеристики",
    "овен трдм202 применение",
]
COMMERCIAL_LLM07 = (
    "Двухканальный измеритель-регулятор ОВЕН ТРМ202 подходит для автоматизации "
    "технологических процессов, требующих контроля и регулирования двух "
    "независимых параметров. Подходит специалистам по промышленной "
    "автоматизации и инженерным службам предприятий."
)


def load_product(identifier: str) -> ProductInput:
    manifest = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["items"] if item["id"] == identifier)
    return ProductInput.model_validate_json(
        (ROOT / entry["input_file"]).read_text(encoding="utf-8")
    )


def trm202() -> ProductInput:
    return load_product("owen_trm202")


def make_card(
    item: ProductInput,
    *,
    seo: str = SEO_LLM07,
    queries: list[str] | None = None,
    note: str = COMMERCIAL_LLM07,
) -> ProductCard:
    return ProductCard(
        seo_title="Двухканальный измеритель-регулятор ОВЕН ТРМ202",
        seo_description=seo,
        search_queries=QUERIES_LLM07 if queries is None else queries,
        commercial_note=note,
        specifications=dict(item.specs),
    )


def test_exact_llm07_response_has_three_independent_blockers() -> None:
    item = trm202()
    assert len(SEO_LLM07) == 725
    issues = editorial_claim_warnings(item, make_card(item))
    assert len(issues) == 3
    assert any("обозначение модели" in text for text in issues)
    assert any("Независимость" in text for text in issues)
    assert any("Удалённое управление" in text for text in issues)
    result = validate_generated_card(item, make_card(item))
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert len([w for w in result.warnings if w in issues]) == 3


@pytest.mark.parametrize(
    "queries",
    [
        ["овен трдм202 применение", "овен трм202 характеристики", "овен регулятор"],
        ["овен трм203 применение", "овен трм202 характеристики", "овен регулятор"],
    ],
)
def test_near_model_codes_are_rejected(queries: list[str]) -> None:
    item = trm202()
    card = make_card(
        item,
        seo="В исходных данных указаны технические параметры прибора.",
        note="При заказе сверить параметры.",
        queries=queries,
    )
    assert any("обозначение модели" in w for w in editorial_claim_warnings(item, card))


def test_correct_model_code_is_allowed() -> None:
    item = trm202()
    card = make_card(
        item,
        queries=["овен трм202 применение", "овен трм202 характеристики"],
        note="Перед выбором сверить технические параметры с проектом.",
    )
    assert not any("обозначение модели" in w for w in editorial_claim_warnings(item, card))


def test_independent_parameters_require_structured_source() -> None:
    item = trm202()
    card = make_card(
        item,
        seo="Тестовый прибор.",
        queries=["овен трм202"],
        note="Регулирование двух независимых параметров.",
    )
    assert any("Независимость" in w for w in editorial_claim_warnings(item, card))
    with_proof = item.model_copy(
        update={
            "specs": {
                **item.specs,
                "режим регулирования": "регулирование двух независимых параметров",
            }
        }
    )
    assert not any("Независимость" in w for w in editorial_claim_warnings(with_proof, card))


def test_remote_monitoring_requires_structured_source() -> None:
    item = trm202()
    card = make_card(
        item,
        seo="RS-485 обеспечивает удалённый мониторинг и управление.",
        queries=["овен трм202"],
        note="Сверить данные.",
    )
    assert any("Удалённое управление" in w for w in editorial_claim_warnings(item, card))
    with_proof = item.model_copy(
        update={
            "specs": {**item.specs, "возможности интерфейса": "удалённый мониторинг и управление"}
        }
    )
    assert not any("Удалённое управление" in w for w in editorial_claim_warnings(with_proof, card))


def test_neutral_interface_and_no_independence_are_allowed() -> None:
    item = trm202()
    safe = make_card(
        item,
        seo="Интерфейс RS-485 указан в характеристиках прибора.",
        queries=grounded_search_queries(item),
        note="При выборе уточняют параметры серии и условия установки.",
    )
    assert editorial_claim_warnings(item, safe) == []


def test_specific_new_rules_do_not_flag_other_recorded_fallbacks() -> None:
    # Existing fallback texts from LLM-07 remain within the new rule boundary.
    for identifier in ("rosma_bt_51_211", "owen_pd200"):
        item = load_product(identifier)
        card = ProductCard(
            seo_title=item.name,
            seo_description="Значения уточняются по документации производителя.",
            search_queries=grounded_search_queries(item),
            commercial_note="Перед заказом сверяют характеристики.",
            specifications=dict(item.specs),
        )
        assert editorial_claim_warnings(item, card) == []


class Provider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = 0

    def generate_text(self, **_kwargs: Any) -> str:
        self.calls += 1
        if not self.responses:
            raise AssertionError("Unexpected extra live-model call")
        return self.responses.pop(0)


def raw_response(item: ProductInput, card: ProductCard) -> str:
    return json.dumps(
        {
            "seo_title": card.seo_title,
            "seo_description": card.seo_description,
            "search_queries": card.search_queries,
            "commercial_note": card.commercial_note,
        },
        ensure_ascii=False,
    )


def test_real_llm07_reply_cannot_receive_llm_grounded_auto_approval() -> None:
    item = trm202()
    draft = raw_response(item, make_card(item))
    provider = Provider(draft, draft)
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source != GenerationSource.LLM_GROUNDED
    assert result.card.specifications == item.specs
    assert result.status in {GenerationStatus.READY_FOR_REVIEW, GenerationStatus.REQUIRES_REVISION}
    if result.status == GenerationStatus.READY_FOR_REVIEW:
        assert result.generation_meta.seo_source == GenerationSource.FALLBACK


def test_corrected_safe_short_reply_can_still_be_grounded() -> None:
    item = trm202()
    safe_seo = SEO_LLM07.replace(
        "Интерфейс RS-485 обеспечивает удалённый мониторинг и управление.",
        "Интерфейс RS-485 указан в характеристиках прибора.",
    )
    safe_note = "При выборе исполнения сверяют параметры и требования к установке."
    draft = raw_response(
        item, make_card(item, seo=safe_seo, queries=grounded_search_queries(item), note=safe_note)
    )
    provider = Provider(draft)
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 1
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.LLM_GROUNDED
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert (result.card.seo_description or "").startswith(safe_seo)
    assert result.card.specifications == item.specs
