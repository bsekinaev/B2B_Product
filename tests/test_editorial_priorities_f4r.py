"""V013-04E-F4R: полезные признаки вместо случайного порядка полей."""

import json
from pathlib import Path

import pytest

from app.editorial_priorities import ranked_spec_names
from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.grounded_queries import grounded_search_queries
from app.schemas import GenerationSource, GenerationStatus, ProductInput

ROOT = Path(__file__).resolve().parents[1]
ITEMS = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))[
    "items"
]


def load(identifier: str) -> ProductInput:
    item = next(row for row in ITEMS if row["id"] == identifier)
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("owen_trm202", ("количество измерительных каналов", "входные сигналы")),
        ("owen_trm500", ("количество основных измерительных входов", "дополнительный вход")),
        ("owen_trm151", ("количество входов датчиков", "количество выходных элементов")),
        ("owen_si8", ("количество входов", "количество выходных устройств")),
        ("owen_2trm1", ("количество универсальных входов", "типы выходных устройств")),
    ],
)
def test_selection_prefers_source_inputs_and_outputs(
    identifier: str, expected: tuple[str, str]
) -> None:
    product = load(identifier)
    preferred = ranked_spec_names(product.specs, "controller", 2)
    assert preferred == list(expected)
    seo = grounded_seo_description(product)
    assert seo is not None
    # Dense sources may omit the editorial lead-in to satisfy the SEO limit.
    intro = seo.split("\n\n", 1)[0]
    if "При подборе измерительного прибора сверяют" in intro:
        assert all(f"«{name}»" in intro for name in expected)
        assert "«тип»" not in intro
        assert "«частота питания»" not in intro


@pytest.mark.parametrize("identifier", ["owen_trm500", "owen_trm10", "owen_trm151", "owen_si8"])
def test_search_avoids_long_measurement_names(identifier: str) -> None:
    product = load(identifier)
    queries = grounded_search_queries(product)
    assert 3 <= len(queries) <= 5
    assert all("(серия)" not in q.casefold() for q in queries)
    assert not any("погрешность для термопар с компенсацией" in q for q in queries)
    assert not any("погрешность при работе с термопреобразователем" in q for q in queries)
    assert len(queries) == len({" ".join(q.split()).casefold() for q in queries})


@pytest.mark.parametrize(
    "identifier",
    ["owen_trm1", "owen_2trm1", "owen_trm202", "owen_trm500", "owen_trm151", "owen_si8"],
)
def test_commercial_prioritizes_instrument_inputs_and_outputs(identifier: str) -> None:
    product = load(identifier)
    selected = ranked_spec_names(product.specs, "controller", 3)
    note = grounded_commercial_note(product, list(product.specs)[:3])
    assert len(selected) == 3
    assert all(name in note for name in selected)
    assert "частота питания" not in selected
    assert "потребляемая мощность" not in selected
    assert "тип" not in selected
    assert "гарантия" not in note.casefold()


def test_no_external_facts_and_no_empty_selection() -> None:
    specs = {
        "тип": "контроллер",
        "частота питания": "50 Гц",
        "статус исполнения": "варианты серии; артикул не выбран",
        "погрешность с термопарой": "",
    }
    expected = ranked_spec_names(specs, "controller", 3)
    assert expected == ["частота питания"]
    assert ranked_spec_names(specs, "thermometer", 3) == []
    assert ranked_spec_names(specs, "controller", 0) == []
    assert specs["погрешность с термопарой"] == ""


class BadTextProvider:
    def __init__(self, product: ProductInput) -> None:
        self.product = product
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return json.dumps(
            {
                "seo_title": self.product.name,
                "seo_description": "Слишком коротко.",
                "search_queries": [
                    self.product.name,
                    self.product.name + " характеристики",
                    self.product.name + " параметры",
                ],
                "commercial_note": "Гарантия 25 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize("item", ITEMS, ids=[row["id"] for row in ITEMS])
def test_complete_20_card_fallback_contract(item: dict) -> None:
    product = load(item["id"])
    original = dict(product.specs)
    provider = BadTextProvider(product)
    result = generate_card(product, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.warnings == []
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert result.card.specifications == original
    assert product.specs == original
    seo = result.card.seo_description or ""
    assert 800 <= len(seo) <= 1200
    for name, value in original.items():
        assert seo.count(f"{name} — {value.strip()}") == 1
    queries = result.card.search_queries
    assert 3 <= len(queries) <= 5
    assert not any("(серия)" in query.casefold() for query in queries)
