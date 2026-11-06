"""Регрессионные проверки предметных поисковых запросов v0.1.3."""

import json
from pathlib import Path

import pytest

from app.generator import generate_card
from app.grounded_queries import grounded_search_queries
from app.schemas import GenerationSource, GenerationStatus, ProductInput

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
ITEMS = MANIFEST["items"]


def load(item: dict) -> ProductInput:
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


class ShortProvider:
    def __init__(self, product: ProductInput):
        self.product = product
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return json.dumps(
            {
                "seo_title": self.product.name,
                "seo_description": "Короткий текст.",
                "search_queries": [
                    self.product.name,
                    self.product.name + " характеристики",
                    self.product.name + " параметры",
                ],
                "commercial_note": "Гарантия 25 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize("item", ITEMS, ids=[item["id"] for item in ITEMS])
def test_query_set_is_grounded_and_unique(item: dict) -> None:
    product = load(item)
    specs = dict(product.specs)

    queries = grounded_search_queries(product)
    normalized = [" ".join(q.split()).casefold() for q in queries]

    assert 3 <= len(queries) <= 5
    assert len(normalized) == len(set(normalized))
    assert queries[0] == product.name
    assert product.specs == specs

    for query in queries:
        assert query.strip()
        assert "гарантия" not in query.casefold()
        assert "доставка" not in query.casefold()
        assert "скидка" not in query.casefold()

    is_series = any("варианты серии" in value.casefold() for value in product.specs.values())
    variant_query = f"{product.name} варианты исполнения"

    assert (variant_query in queries) == is_series


@pytest.mark.parametrize("item", ITEMS, ids=[item["id"] for item in ITEMS])
def test_generator_uses_new_queries_in_fallback(item: dict) -> None:
    product = load(item)
    provider = ShortProvider(product)

    result = generate_card(product, provider)

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.specifications == product.specs
    assert result.card.search_queries == grounded_search_queries(product)
    assert result.warnings == []
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert 1 <= provider.calls <= 2


@pytest.mark.parametrize(
    ("identifier", "attribute"),
    [
        ("meter_dm02_series", "класс точности"),
        ("rosma_bt_51_211", "диапазон показаний"),
        ("owen_2trm1", "количество универсальных входов"),
        ("owen_pd150", "класс точности"),
        ("owen_pd200", "основная погрешность"),
    ],
)
def test_category_prioritizes_selection_attribute(
    identifier: str,
    attribute: str,
) -> None:
    item = next(i for i in ITEMS if i["id"] == identifier)
    product = load(item)
    queries = grounded_search_queries(product)

    assert f"{product.name} {attribute}" in queries
    assert f"{product.name} тип" not in queries


def test_optional_interface_is_not_claimed_unconditionally() -> None:
    product = ProductInput(
        name="ОВЕН ТЕСТ (серия)",
        manufacturer="ОВЕН",
        specs={
            "тип": "измеритель-регулятор",
            "интерфейс связи": "RS-485, зависит от исполнения",
            "количество универсальных входов": "2",
            "напряжение питания": "220 В",
        },
    )

    queries = grounded_search_queries(product)

    assert 3 <= len(queries) <= 5
    assert not any("RS-485" in query for query in queries)
    assert not any("гарантия" in query.casefold() for query in queries)


def test_series_query_requires_source_evidence() -> None:
    product = ProductInput(
        name="Манометр ТЕСТ (серия)",
        manufacturer="Завод",
        specs={
            "тип": "манометр",
            "диапазон": "0–1 МПа",
            "класс точности": "1,5",
        },
    )

    queries = grounded_search_queries(product)

    assert not any("варианты исполнения" in q for q in queries)


def test_duplicate_category_query_is_removed() -> None:
    product = ProductInput(
        name="Завод манометр",
        manufacturer="Завод",
        specs={
            "тип": "манометр",
            "класс точности": "1,5",
            "диаметр корпуса": "100 мм",
            "диапазон": "0–1 МПа",
        },
    )

    queries = grounded_search_queries(product)

    assert 3 <= len(queries) <= 5
    assert queries.count("Завод манометр") == 1
    assert len(set(queries)) == len(queries)
