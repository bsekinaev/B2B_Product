"""Офлайн-проверки строгого выпускного барьера для двух экспортированных карточек."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.grounded_copy import grounded_commercial_note, grounded_seo_description
from app.schemas import ProductCard, ProductInput
from app.validation import validate_generated_card
from scripts.check_live_results import SubmissionCheckError, check_exported_results
from scripts.run_acceptance import load_product


def _sample_export(name: str) -> dict[str, Any]:
    product = ProductInput.model_validate(load_product(name))
    description = grounded_seo_description(product)
    assert description is not None
    card = ProductCard(
        seo_title=product.name,
        seo_description=description,
        specifications=product.specs,
        search_queries=[
            f"{product.name} характеристики",
            f"{product.name} описание",
            f"{product.name} производитель",
        ],
        commercial_note=grounded_commercial_note(product),
    )
    result = validate_generated_card(product, card)
    assert result.status.value == "ready_for_review"
    return {
        "source": "live_gigachat_api",
        "review_status": "human_review_required",
        "fixture": f"examples/products/{name}.json",
        "product": product.model_dump(),
        "result": result.model_dump(mode="json"),
    }


def _write_exports(directory: Path) -> dict[str, dict[str, Any]]:
    directory.mkdir(parents=True, exist_ok=True)
    exports = {name: _sample_export(name) for name in ("manometer", "thermometer")}
    for name, data in exports.items():
        (directory / f"{name}.live.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    return exports


def test_two_formally_valid_exports_are_accepted(tmp_path: Path) -> None:
    _write_exports(tmp_path)
    results = check_exported_results(tmp_path)
    assert len(results) == 2
    assert all(row["status"] == "ready_for_review" for row in results)
    assert all(row["human_review_required"] for row in results)


def test_missing_second_export_blocks_submission(tmp_path: Path) -> None:
    _write_exports(tmp_path)
    (tmp_path / "thermometer.live.json").unlink()
    with pytest.raises(SubmissionCheckError, match="файл не найден"):
        check_exported_results(tmp_path)


@pytest.mark.parametrize("field", ["seo_description", "commercial_note"])
def test_short_or_blank_content_blocks_submission(tmp_path: Path, field: str) -> None:
    exports = _write_exports(tmp_path)
    replacement = "" if field == "commercial_note" else "Коротко"
    exports["manometer"]["result"]["card"][field] = replacement
    (tmp_path / "manometer.live.json").write_text(
        json.dumps(exports["manometer"], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SubmissionCheckError, match="требует исправления"):
        check_exported_results(tmp_path)


def test_forged_laboratory_claim_blocks_submission(tmp_path: Path) -> None:
    exports = _write_exports(tmp_path)
    exports["thermometer"]["result"]["card"]["commercial_note"] += (
        " Гарантирована высокая точность лабораторных измерений."
    )
    (tmp_path / "thermometer.live.json").write_text(
        json.dumps(exports["thermometer"], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SubmissionCheckError, match="требует исправления"):
        check_exported_results(tmp_path)


def test_modified_original_specifications_block_submission(tmp_path: Path) -> None:
    exports = _write_exports(tmp_path)
    exports["manometer"]["result"]["card"]["specifications"]["класс точности"] = "0,5"
    (tmp_path / "manometer.live.json").write_text(
        json.dumps(exports["manometer"], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SubmissionCheckError, match="характеристики отличаются"):
        check_exported_results(tmp_path)


def test_stale_product_fixture_blocks_submission(tmp_path: Path) -> None:
    exports = _write_exports(tmp_path)
    exports["thermometer"]["product"]["name"] = "Неверная модель"
    (tmp_path / "thermometer.live.json").write_text(
        json.dumps(exports["thermometer"], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SubmissionCheckError, match="входные данные отличаются"):
        check_exported_results(tmp_path)
