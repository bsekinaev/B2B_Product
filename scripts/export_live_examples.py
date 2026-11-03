"""Явный экспорт двух живых черновиков для ручного ревью перед сдачей.

Команда записывает только демонстрационные товары; не запускается без флага.
В Git могут попасть галлюцинации модели: результаты не являются утверждёнными.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import GenerationResult
from scripts.run_acceptance import ROOT, load_product

EXAMPLES = ("manometer", "thermometer")
DESTINATION = ROOT / "examples" / "results"


class ExampleExportError(RuntimeError):
    """Контролируемая ошибка подготовки примеров, без данных стороннего API."""


def export_live_examples(
    *, output_dir: Path = DESTINATION, client_factory: Any = TestClient
) -> list[Path]:
    """Проверить оба ответа перед записью; существующие файлы не заменять."""
    paths = [output_dir / f"{name}.live.json" for name in EXAMPLES]
    if any(path.exists() for path in paths):
        raise ExampleExportError("Примеры уже существуют; сначала проверьте их")

    records: list[dict[str, Any]] = []
    with client_factory(app) as client:
        for name in EXAMPLES:
            product = load_product(name)
            response = client.post("/generate", json=product)
            if response.status_code != 200:
                raise ExampleExportError(f"{name}: HTTP {response.status_code}")
            try:
                result = GenerationResult.model_validate(response.json())
            except (ValueError, TypeError):
                raise ExampleExportError(f"{name}: некорректная структура результата") from None
            if result.card.specifications != product["specs"]:
                raise ExampleExportError(f"{name}: характеристики изменены")

            records.append(
                {
                    "source": "live_gigachat_api",
                    "review_status": "human_review_required",
                    "fixture": f"examples/products/{name}.json",
                    "product": product,
                    "result": result.model_dump(mode="json"),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    for path, item in zip(paths, records, strict=True):
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Два live-примера для ручного ревью")
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Явно разрешить до четырёх GigaChat-вызовов и сохранение черновиков",
    )
    args = parser.parse_args()

    if not args.confirm_live:
        parser.error("Нужен флаг --confirm-live (вызовы GigaChat расходуют квоту)")

    try:
        paths = export_live_examples()
    except (ExampleExportError, OSError) as exc:
        # Не выводим тело ошибок, реквизиты и исходный текст внешнего SDK.
        print(f"LIVE EXAMPLES: FAIL ({type(exc).__name__})")
        return 1

    for path in paths:
        print(f"EXPORTED: {path.relative_to(ROOT)}")
    print("LIVE EXAMPLES: WRITTEN; HUMAN REVIEW REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
