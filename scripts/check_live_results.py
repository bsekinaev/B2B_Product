"""Строгая проверка экспортированных live-результатов перед сдачей.

Не обращается в GigaChat и не публикует содержимое карточек.
Успех означает прохождение формальных критериев, не семантическое
подтверждение паспортных характеристик: требуется редакторское ревью.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas import GenerationResult, GenerationStatus, ProductInput
from app.validation import validate_generated_card
from scripts.export_live_examples import EXAMPLES
from scripts.run_acceptance import ROOT, load_product


class SubmissionCheckError(ValueError):
    """Формальные требования к результатам двух товаров не выполнены."""


def check_exported_results(directory: Path) -> list[dict[str, Any]]:
    """Проверить ровно два ожидаемых результата без сетевых запросов."""
    reports: list[dict[str, Any]] = []
    for name in EXAMPLES:
        path = directory / f"{name}.live.json"
        if not path.is_file():
            raise SubmissionCheckError(f"{name}: файл не найден")
        try:
            exported = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(exported, dict):
                raise ValueError("not an object")
            if exported.get("source") != "live_gigachat_api":
                raise ValueError("not a live export")
            if exported.get("review_status") != "human_review_required":
                raise ValueError("missing review marker")
            if exported.get("fixture") != f"examples/products/{name}.json":
                raise ValueError("fixture mismatch")
            product = ProductInput.model_validate(exported["product"])
            result = GenerationResult.model_validate(exported["result"])
        except (OSError, KeyError, ValueError, TypeError, ValidationError) as exc:
            raise SubmissionCheckError(f"{name}: некорректный экспорт") from exc

        if product.model_dump() != load_product(name):
            raise SubmissionCheckError(f"{name}: входные данные отличаются от примера")
        if result.card.specifications != product.specs:
            raise SubmissionCheckError(f"{name}: характеристики отличаются от источника")

        checked = validate_generated_card(
            product, result.card, missing_fields=result.missing_fields
        )
        if (
            result.status != GenerationStatus.READY_FOR_REVIEW
            or checked.status != GenerationStatus.READY_FOR_REVIEW
            or result.warnings
            or result.missing_fields
            or checked.warnings
            or checked.missing_fields
        ):
            raise SubmissionCheckError(
                f"{name}: карточка требует исправления; рассмотрите предупреждения JSON"
            )

        reports.append(
            {
                "product": name,
                "status": result.status.value,
                "seo_description_characters": len(result.card.seo_description or ""),
                "commercial_note_filled": bool((result.card.commercial_note or "").strip()),
                "search_queries": len(result.card.search_queries),
                "technical_specs_unchanged": True,
                "human_review_required": True,
            }
        )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить два ранее экспортированных live-результата без сети"
    )
    parser.add_argument(
        "--dir", type=Path, default=ROOT / "examples" / "results", help="Папка с *.live.json"
    )
    args = parser.parse_args()

    try:
        rows = check_exported_results(args.dir)
    except SubmissionCheckError as exc:
        # Не печатаем JSON с возможными закрытыми сведениями.
        print(f"SUBMISSION OUTPUTS: NOT PASSED ({exc})")
        return 1

    for row in rows:
        print(
            f"{row['product']}: {row['status']}; "
            f"SEO={row['seo_description_characters']}; "
            f"commercial=FILLED; specs=UNCHANGED"
        )
    print("SUBMISSION OUTPUTS: FORMAL PASS; HUMAN REVIEW STILL REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
