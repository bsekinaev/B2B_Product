"""LLM-04: regression guards justified by recorded real model errors (offline)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_queries import grounded_search_queries
from app.llm.prompts import SYSTEM_PROMPT, build_refinement_prompt
from app.schemas import GenerationSource, ProductCard, ProductInput
from app.validation import validate_generated_card
from app.variant_claims import variant_claim_warnings

ROOT = Path(__file__).resolve().parents[1]


def load(identifier: str) -> ProductInput:
    manifest = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["items"] if item["id"] == identifier)
    return ProductInput.model_validate_json(
        (ROOT / entry["input_file"]).read_text(encoding="utf-8")
    )


def card(product: ProductInput, description: str) -> ProductCard:
    return ProductCard(
        seo_title=product.name,
        seo_description=description,
        search_queries=[product.name, f"{product.name} характеристики", f"{product.name} каталог"],
        commercial_note="Перед заказом уточнить исполнение по документации.",
        specifications=dict(product.specs),
    )


@pytest.mark.parametrize(
    "identifier, claim",
    [
        (
            "rosma_bt_51_211",
            "Степень защиты корпуса IP54 обеспечивает защиту от пыли и водяных струй.",
        ),
        ("owen_pd200", "Степень защиты IP65 обеспечивает защиту от пыли и водяных струй."),
    ],
)
def test_unsourced_ip_explanation_is_blocking(identifier: str, claim: str) -> None:
    item = load(identifier)
    result = validate_generated_card(item, card(item, claim))
    assert result.status.value == "requires_revision"
    assert any("Расшифровка степени защиты IP" in w for w in result.warnings)


@pytest.mark.parametrize(
    "identifier, claim",
    [
        ("rosma_bt_51_211", "Степень защиты корпуса — IP54."),
        ("owen_pd200", "Степень защиты оболочки — IP65."),
    ],
)
def test_ip_class_without_interpretation_is_allowed(identifier: str, claim: str) -> None:
    item = load(identifier)
    result = validate_generated_card(item, card(item, claim))
    assert not any("Расшифровка степени защиты IP" in w for w in result.warnings)


def test_ip_details_supported_in_structured_data() -> None:
    item = load("owen_pd200")
    item = item.model_copy(
        update={
            "specs": {
                **item.specs,
                "степень защиты оболочки": "IP65; защита от пыли и водяных струй",
            }
        }
    )
    result = validate_generated_card(
        item, card(item, "Степень защиты IP65 обеспечивает защиту от пыли и водяных струй.")
    )
    assert not any("Расшифровка степени защиты IP" in w for w in result.warnings)


@pytest.mark.parametrize(
    "text",
    [
        "Прибор оснащён интерфейсами 4…20 мА + HART и RS-485 Modbus.",
        "Доступны интерфейсы HART и RS-485.",
    ],
)
def test_unqualified_hart_rs485_pair_is_blocking(text: str) -> None:
    item = load("owen_pd200")
    result = variant_claim_warnings(item, card(item, text))
    assert any("Альтернативные интерфейсы" in w for w in result)


@pytest.mark.parametrize(
    "text",
    [
        "Варианты серии включают HART и RS-485.",
        "HART и RS-485 не работают одновременно.",
        "Для исполнения выбирают HART или RS-485.",
    ],
)
def test_explicit_alternatives_remain_allowed(text: str) -> None:
    item = load("owen_pd200")
    assert not any(
        "Альтернативные интерфейсы" in w for w in variant_claim_warnings(item, card(item, text))
    )


class Provider:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls = 0

    def generate_text(self, **_kwargs: Any) -> str:
        self.calls += 1
        return self.answers.pop(0)


def model_answer(item: ProductInput, description: str) -> str:
    title = f"{item.name} — характеристики"
    if len(title) > 70:
        title = item.name
    return json.dumps(
        {
            "seo_title": title,
            "seo_description": description,
            "search_queries": grounded_search_queries(item),
            "commercial_note": grounded_commercial_note(item, list(item.specs)[:3]),
        },
        ensure_ascii=False,
    )


def test_partial_refinement_is_not_traced_as_final_approval() -> None:
    item = load("rosma_bt_51_211")
    original = "Термометр РОСМА: краткий черновик на исходных характеристиках."
    revised = original * 5
    assert len(revised) < 800
    provider = Provider(model_answer(item, original), model_answer(item, revised))
    result = generate_card(item, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert "refinement_partial" in result.generation_meta.reason_codes
    assert "refinement_selected" not in result.generation_meta.reason_codes
    assert "fallback_selected" in result.generation_meta.reason_codes


def test_prompt_has_length_plan_and_series_guard() -> None:
    assert "850–1100" in SYSTEM_PROMPT
    assert "ТОЛЬКО в seo_description" in SYSTEM_PROMPT
    assert "Не называй водяные струи защитой IP54" in SYSTEM_PROMPT
    assert "сертификаты" in SYSTEM_PROMPT
    prompt = build_refinement_prompt(load("owen_trm202"), 732)
    assert "850–1100" in prompt
    assert "четырёх абзацев" in prompt
    assert "не добавляй" in prompt.casefold()
