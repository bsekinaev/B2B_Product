"""V013-04E-F3: поисковое намерение без служебного суффикса серии."""

import json
from pathlib import Path

import pytest

from app.generator import generate_card
from app.grounded_queries import _search_identity, grounded_search_queries
from app.schemas import GenerationSource, GenerationStatus, ProductInput
from app.variant_scope import VariantScope, variant_scope

ROOT = Path(__file__).resolve().parents[1]
ITEMS = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))[
    "items"
]


def load(item: dict) -> ProductInput:
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


class BadTextProvider:
    def __init__(self, product: ProductInput):
        self.product = product
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return json.dumps(
            {
                "seo_title": self.product.name,
                "seo_description": "Слишком короткое описание.",
                "search_queries": [
                    self.product.name,
                    self.product.name + " характеристики",
                    self.product.name + " параметры",
                ],
                "commercial_note": "Гарантия 50 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize("item", ITEMS, ids=[i["id"] for i in ITEMS])
def test_natural_queries_match_exact_scope_and_facts(item: dict) -> None:
    product = load(item)
    source_specs = dict(product.specs)
    queries = grounded_search_queries(product)
    identity = _search_identity(product)
    scope = variant_scope(product)

    assert 3 <= len(queries) <= 5
    assert len(queries) == len({" ".join(q.split()).casefold() for q in queries})
    assert queries[0] == identity
    assert not any("(серия)" in q.casefold() for q in queries)
    assert product.specs == source_specs
    assert not any("RS-485" in query for query in queries)
    assert not any("гарант" in query.casefold() for query in queries)
    assert not any("доставк" in query.casefold() for query in queries)

    variant_query = f"{identity} варианты исполнения"
    article_query = f"{identity} подбор артикула"
    assert (variant_query in queries) == (scope == VariantScope.EXPLICIT_ALTERNATIVES)
    assert (article_query in queries) == (scope == VariantScope.STATUS_ONLY)


@pytest.mark.parametrize("item", ITEMS, ids=[i["id"] for i in ITEMS])
def test_full_fallback_keeps_http_contract_equivalent(item: dict) -> None:
    product = load(item)
    provider = BadTextProvider(product)
    result = generate_card(product, provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert result.card.specifications == product.specs
    assert result.card.search_queries == grounded_search_queries(product)
    assert result.warnings == []
    assert 800 <= len(result.card.seo_description or "") <= 1200


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ОВЕН ПД200 (серия)", "ОВЕН ПД200"),
        ("ОВЕН ПД200 (СЕРИЯ) ", "ОВЕН ПД200"),
        ("РОСМА G1/2 (серия) вариант", "РОСМА G1/2 (серия) вариант"),
        ("ОВЕН ТРМ1", "ОВЕН ТРМ1"),
        ("(серия)", "(серия)"),
    ],
)
def test_only_trailing_editorial_marker_is_removed(name: str, expected: str) -> None:
    product = ProductInput(name=name, manufacturer="Завод", specs={"тип": "регулятор"})
    assert _search_identity(product) == expected


def test_unique_queries_when_manufacturer_and_kind_equal_name() -> None:
    product = ProductInput(
        name="Завод манометр (серия)",
        manufacturer="Завод",
        specs={
            "тип": "манометр",
            "класс точности": "1,5",
            "диаметр корпуса": "100 мм",
            "статус исполнения": "варианты серии; точная модификация не выбрана",
        },
    )
    queries = grounded_search_queries(product)
    assert 3 <= len(queries) <= 5
    assert len(queries) == len(set(queries))
    assert "Завод манометр подбор артикула" in queries
