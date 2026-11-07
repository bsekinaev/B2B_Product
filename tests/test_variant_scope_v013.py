"""V013-04E-F2: честные оговорки о вариантах изделий и сериях."""

import json
from pathlib import Path

import pytest

from app.generator import generate_card
from app.grounded_commercial import grounded_commercial_note
from app.grounded_copy import grounded_seo_description
from app.schemas import GenerationSource, GenerationStatus, ProductInput
from app.variant_scope import VariantScope, variant_scope

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "examples/live_batch/manifest.json").read_text(encoding="utf-8"))
ITEMS = MANIFEST["items"]


def load(item: dict) -> ProductInput:
    return ProductInput.model_validate_json((ROOT / item["input_file"]).read_text(encoding="utf-8"))


class ShortProvider:
    """Вынуждает безопасный fallback, но не вызывает GigaChat."""

    def __init__(self, product: ProductInput) -> None:
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
                    f"{self.product.name} характеристики",
                    f"{self.product.name} параметры",
                ],
                "commercial_note": "Гарантия 25 лет.",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize("item", ITEMS, ids=[item["id"] for item in ITEMS])
def test_f2_scope_and_full_fallback(item: dict) -> None:
    product = load(item)
    scope = variant_scope(product)
    source_specs = dict(product.specs)
    provider = ShortProvider(product)
    result = generate_card(product, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.generation_meta is not None
    assert result.generation_meta.seo_source == GenerationSource.FALLBACK
    assert provider.calls == 2
    assert result.warnings == []
    assert result.card.specifications == source_specs
    assert product.specs == source_specs
    seo = result.card.seo_description or ""
    note = result.card.commercial_note or ""
    assert 800 <= len(seo) <= 1200
    for name, value in product.specs.items():
        assert seo.count(f"{name} — {value.strip()}") == 1

    if item["id"] == "rosma_bt_51_211":
        assert scope == VariantScope.CONFIGURED_VARIANT
        assert "Карточка относится к серии без выбранного артикула" not in seo
    elif scope == VariantScope.STATUS_ONLY:
        # Не приписываем всем характеристикам статус альтернатив без свидетельств.
        assert "Для серии приведены характеристики альтернативных исполнений" not in seo
        assert "Перечень не описывает одну готовую конфигурацию" not in seo
        assert "альтернативные характеристики нельзя" not in note
        assert "перечисленные варианты не подтверждают" not in note
        assert "артикул" in note
        assert "по документации" in note
    elif scope == VariantScope.EXPLICIT_ALTERNATIVES:
        assert any(
            "варианты серии" in value.casefold() and name.casefold() != "статус исполнения"
            for name, value in product.specs.items()
        )
    else:
        pytest.fail(f"Unexpected scope for {item['id']}: {scope}")


def test_scope_distribution_matches_source_manifest() -> None:
    categories = [variant_scope(load(item)) for item in ITEMS]
    assert categories.count(VariantScope.EXPLICIT_ALTERNATIVES) == 9
    assert categories.count(VariantScope.STATUS_ONLY) == 10
    assert categories.count(VariantScope.CONFIGURED_VARIANT) == 1


@pytest.mark.parametrize(
    ("specs", "expected"),
    [
        ({"тип": "манометр"}, VariantScope.CONFIGURED_VARIANT),
        (
            {"статус исполнения": "варианты серии; точная модификация не выбрана"},
            VariantScope.STATUS_ONLY,
        ),
        (
            {"тип": "прибор", "диапазон": "0–1 МПа, варианты серии"},
            VariantScope.EXPLICIT_ALTERNATIVES,
        ),
        (
            {
                "статус исполнения": "варианты серии; точная модификация не выбрана",
                "выходные устройства": "Р / К, варианты серии",
            },
            VariantScope.EXPLICIT_ALTERNATIVES,
        ),
    ],
)
def test_scope_only_uses_values_of_source_specs(specs: dict, expected: VariantScope) -> None:
    product = ProductInput(name="Прибор ТЕСТ (серия)", manufacturer="Завод", specs=specs)
    assert variant_scope(product) == expected


def test_status_only_commercial_has_no_fabricated_alternatives() -> None:
    product = ProductInput(
        name="ОВЕН ТЕСТ (серия)",
        manufacturer="ОВЕН",
        specs={
            "тип": "регулятор",
            "напряжение питания": "220 В",
            "статус исполнения": "варианты серии; точная модификация не выбрана",
        },
    )
    note = grounded_commercial_note(product, list(product.specs))
    assert "артикул" in note
    assert "альтернативные характеристики нельзя" not in note


def test_explicit_alternatives_keep_caution() -> None:
    item = next(row for row in ITEMS if row["id"] == "owen_2trm1")
    product = load(item)
    assert variant_scope(product) == VariantScope.EXPLICIT_ALTERNATIVES
    note = grounded_commercial_note(product, list(product.specs))
    assert "альтернативные характеристики" in note
    assert grounded_seo_description(product) is not None
