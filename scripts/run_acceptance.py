"""Воспроизводимая HTTP-приёмка; live-режим требует явного флага.

Офлайн-черновики — только тестовые фикстуры, а не рекламные тексты.
Ни один режим не публикует карточки и не пишет секреты в отчёт.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ProductInput

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "products"


@dataclass(frozen=True)
class AcceptanceCase:
    name: str
    fixture: str
    variant: str
    expected_status: str | None


OFFLINE_CASES = (
    AcceptanceCase("Манометр: формальные ограничения", "manometer", "complete", "ready_for_review"),
    AcceptanceCase(
        "Термометр: формальные ограничения", "thermometer", "complete", "ready_for_review"
    ),
    AcceptanceCase("Недостаточно характеристик", "incomplete", "complete", "insufficient_data"),
    AcceptanceCase("Неподтверждённая гарантия", "manometer", "unsupported", "requires_revision"),
    AcceptanceCase("Короткое SEO-описание", "thermometer", "short", "requires_revision"),
)
LIVE_CASES = (
    AcceptanceCase("Манометр: реальный GigaChat", "manometer", "live", None),
    AcceptanceCase("Термометр: реальный GigaChat", "thermometer", "live", None),
)


def load_product(filename: str) -> dict[str, Any]:
    path = EXAMPLES / f"{filename}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ProductInput.model_validate(raw).model_dump()


def offline_description(product: ProductInput) -> str:
    """Имитировать нужную длину без дополнительных технических утверждений."""
    facts = [product.name, product.manufacturer, product.description or ""]
    facts.extend(f"{key}: {value}" for key, value in product.specs.items())
    segment = "; ".join(facts).replace(".", ";").strip() + "; "
    return (segment * (850 // len(segment) + 2))[:850]


class OfflineProvider:
    """Контракт провайдера без SDK-сети, стоимость API-вызовов равна нулю."""

    def __init__(self, product: ProductInput, variant: str):
        self.product = product
        self.variant = variant

    def generate_text(self, **_kwargs: Any) -> str:
        product = self.product
        description = offline_description(product)
        commercial_note = f"Сведения о {product.name} для редакторской проверки"
        if self.variant == "short":
            description = "Недостаточно сведений для объёмного SEO-описания"
        elif self.variant == "unsupported":
            commercial_note = "Гарантия 20 лет, подтверждена ГОСТ"
        return json.dumps(
            {
                "seo_title": f"{product.name} — характеристики",
                "seo_description": description,
                "search_queries": [
                    f"{product.name} характеристики",
                    f"{product.name} {product.manufacturer}",
                    f"{product.name} описание",
                ],
                "commercial_note": commercial_note,
            },
            ensure_ascii=False,
        )


def run_case(client: TestClient, case: AcceptanceCase, *, live: bool) -> dict[str, Any]:
    """Проверять контракт на реальном HTTP-маршруте, включая сериализацию."""
    product_data = load_product(case.fixture)
    if live:
        response = client.post("/generate", json=product_data)
    else:
        product = ProductInput.model_validate(product_data)
        provider = OfflineProvider(product, case.variant)
        with patch("app.main.GigaChatProvider", return_value=provider):
            response = client.post("/generate", json=product_data)

    if response.status_code != 200:
        # Не выводить тело ошибок: сторонние ответы могут содержать приватные сведения.
        raise RuntimeError(f"{case.name}: HTTP {response.status_code}")

    result = response.json()
    if not isinstance(result, dict) or not isinstance(result.get("card"), dict):
        raise RuntimeError(f"{case.name}: неверная структура ответа")

    card = result["card"]
    if card.get("specifications") != product_data["specs"]:
        raise RuntimeError(f"{case.name}: исходные характеристики были изменены")

    if result.get("status") not in {"ready_for_review", "requires_revision", "insufficient_data"}:
        raise RuntimeError(f"{case.name}: неподдерживаемый статус")

    if case.expected_status and result["status"] != case.expected_status:
        raise RuntimeError(
            f"{case.name}: ожидали {case.expected_status}, получили {result['status']}"
        )

    if not isinstance(result.get("warnings"), list) or not isinstance(
        result.get("missing_fields"), list
    ):
        raise RuntimeError(f"{case.name}: отсутствуют поля диагностики")

    return {
        "case": case.name,
        "mode": "live" if live else "offline",
        "http_status": response.status_code,
        "status": result["status"],
        "specs_unchanged": True,
        "seo_title_chars": len(card.get("seo_title") or ""),
        "seo_description_chars": len(card.get("seo_description") or ""),
        "search_queries_count": len(card.get("search_queries") or []),
        "warnings_count": len(result["warnings"]),
        "missing_fields_count": len(result["missing_fields"]),
        "editorial_review_required": True,
    }


def run_acceptance(*, live: bool = False) -> list[dict[str, Any]]:
    cases = LIVE_CASES if live else OFFLINE_CASES
    with TestClient(app) as client:
        return [run_case(client, case, live=live) for case in cases]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка B2B-генератора через HTTP API")
    parser.add_argument(
        "--live", action="store_true", help="Два товара, до четырёх GigaChat-вызовов (квота)"
    )
    parser.add_argument(
        "--report", action="store_true", help="Записать агрегированный отчёт в artifacts/"
    )
    args = parser.parse_args()

    try:
        rows = run_acceptance(live=args.live)
    except (RuntimeError, OSError, ValueError) as exc:
        # Не печатать значения настроек или ошибки стороннего SDK.
        print(f"ACCEPTANCE: FAIL ({type(exc).__name__})")
        return 1

    for item in rows:
        print(
            f"[{item['mode']}] {item['case']}: HTTP {item['http_status']}; "
            f"status={item['status']}; description={item['seo_description_chars']}; "
            f"warnings={item['warnings_count']}; specs=UNCHANGED"
        )

    if args.report:
        output = ROOT / "artifacts" / "acceptance.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("REPORT: artifacts/acceptance.json (excluded from Git)")

    print("HTTP CONTRACT: PASS; EDITORIAL QUALITY: REQUIRES HUMAN REVIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
