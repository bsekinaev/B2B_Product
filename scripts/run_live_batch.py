"""Контролируемая пакетная генерация через реальный HTTP API.

Без --confirm-live сеть не используется.
Результаты хранятся только в игнорируемом Git каталоге artifacts/.
"""

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

import app.main as api
from app.generator import parse_model_json
from app.llm.client import GigaChatProvider, LLMError
from app.schemas import GenerationResult, ProductInput
from scripts.run_acceptance import content_quality_failures

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("examples/live_batch/manifest.json")
OUTPUT = Path("artifacts/live_batch")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{2,79}")


@dataclass(frozen=True)
class BatchItem:
    identifier: str
    product: ProductInput
    input_sha256: str
    catalog_reference: str
    source_scope: str


def load_manifest(root: Path = ROOT) -> list[BatchItem]:
    """Загрузить только явно перечисленные локальные товары."""
    data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))

    if data.get("schema_version") != 1 or data.get("goal") != 20:
        raise ValueError("Unsupported batch manifest")

    entries = data.get("items")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError("Invalid batch item count")

    items = []
    seen_ids = set()
    seen_products = set()

    for entry in entries:
        identifier = entry["id"]
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise ValueError("Unsafe product identifier")

        if identifier in seen_ids:
            raise ValueError("Duplicate product identifier")

        source = Path(entry["input_file"])
        allowed = {
            Path("examples/submission/products") / f"{identifier}.json",
            Path("examples/live_batch/products") / f"{identifier}.json",
        }

        if source not in allowed:
            raise ValueError("Input file outside permitted directories")

        reference = entry["catalog_reference"]
        parsed = urlsplit(reference)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("Invalid manufacturer reference")

        scope = entry["source_scope"]
        if scope not in {"series", "configured_variant"}:
            raise ValueError("Invalid source scope")

        raw = (root / source).read_bytes()
        product = ProductInput.model_validate_json(raw)

        if sum(bool(value.strip()) for value in product.specs.values()) < 4:
            raise ValueError("Not enough technical specifications")

        identity = (product.manufacturer.casefold(), product.name.casefold())

        if identity in seen_products:
            raise ValueError("Duplicate product model")

        items.append(
            BatchItem(
                identifier=identifier,
                product=product,
                input_sha256=hashlib.sha256(raw).hexdigest(),
                catalog_reference=reference,
                source_scope=scope,
            )
        )

        seen_ids.add(identifier)
        seen_products.add(identity)

    return items


class CallLimitReached(RuntimeError):
    """Защита от неожиданного третьего логического вызова."""


class TracedProvider:
    """Считать вызовы LLM, не сохраняя промпты и сырые ответы."""

    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace

    def generate_text(self, **kwargs: Any) -> str:
        if self.trace["calls"] >= 2:
            raise CallLimitReached()

        self.trace["calls"] += 1
        raw = self.delegate.generate_text(**kwargs)

        try:
            generated = parse_model_json(raw)
        except LLMError:
            pass
        else:
            self.trace["seo_texts"].append(generated.seo_description)

        return raw


def save_record(path: Path, record: dict[str, Any]) -> None:
    """Запретить случайную перезапись результата."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run_batch(
    items: list[BatchItem],
    *,
    root: Path = ROOT,
    max_items: int = 2,
    client_factory: Any = TestClient,
    provider_factory: Any = GigaChatProvider,
) -> int:
    """Выполнять последовательные HTTP-запросы, сохраняя результат каждого."""
    if not 1 <= max_items <= 3:
        raise ValueError("Batch size must be between 1 and 3")

    output = root / OUTPUT
    submitted = 0

    with client_factory(api.app) as client:
        for item in items:
            target = output / f"{item.identifier}.json"

            if target.exists():
                saved = json.loads(target.read_text(encoding="utf-8"))

                if saved.get("input_sha256") != item.input_sha256:
                    raise ValueError("Product changed after previous attempt")

                print(f"SKIP {item.identifier}: recorded attempt exists")
                continue

            if submitted >= max_items:
                break

            trace: dict[str, Any] = {"calls": 0, "seo_texts": []}
            real_payload = item.product.model_dump(mode="json")

            record: dict[str, Any] = {
                "id": item.identifier,
                "source": "live_gigachat_api",
                "catalog_reference": item.catalog_reference,
                "source_scope": item.source_scope,
                "input_sha256": item.input_sha256,
                "product": real_payload,
                "human_review_required": True,
            }

            def factory(
                settings: Any,
                captured_trace: dict[str, Any] = trace,
            ) -> TracedProvider:
                return TracedProvider(
                    provider_factory(settings),
                    captured_trace,
                )

            try:
                with patch.object(api, "GigaChatProvider", factory):
                    response = client.post("/generate", json=real_payload)
            except Exception:
                record.update(
                    http_status=None,
                    error_code="execution_error",
                    content_quality="FAIL",
                    llm_calls=trace["calls"],
                )
                save_record(target, record)
                print(f"FAIL {item.identifier}: execution_error")
                return 1

            submitted += 1
            record["http_status"] = response.status_code
            record["llm_calls"] = trace["calls"]

            if response.status_code != 200:
                record["error_code"] = "http_error"
                record["content_quality"] = "FAIL"
                save_record(target, record)
                print(f"FAIL {item.identifier}: HTTP {response.status_code}")
                return 1

            try:
                result = GenerationResult.model_validate(response.json())
            except (ValueError, TypeError):
                record["error_code"] = "invalid_response"
                record["content_quality"] = "FAIL"
                save_record(target, record)
                print(f"FAIL {item.identifier}: invalid_response")
                return 1

            card = result.card
            row = {
                "status": result.status.value,
                "seo_title_chars": len(card.seo_title or ""),
                "seo_description_chars": len((card.seo_description or "").strip()),
                "search_queries_count": len(card.search_queries),
                "commercial_note_chars": len((card.commercial_note or "").strip()),
                "warnings_count": len(result.warnings),
                "missing_fields_count": len(result.missing_fields),
                "specs_unchanged": card.specifications == item.product.specs,
            }

            failures = content_quality_failures(row)

            if trace["calls"] == 0:
                failures.append("llm_not_observed")

            model_text_match = (
                card.seo_description in trace["seo_texts"] if card.seo_description else False
            )

            record.update(
                result=result.model_dump(mode="json"),
                metrics=row,
                model_seo_text_retained=model_text_match,
                content_quality="FAIL" if failures else "PASS",
                quality_failures=failures,
                review_status="human_review_required",
            )

            save_record(target, record)

            verdict = record["content_quality"]
            print(
                f"{verdict} {item.identifier}: "
                f"SEO={row['seo_description_chars']}; "
                f"calls={trace['calls']}; "
                f"model_seo_match={model_text_match}"
            )

            if failures:
                return 2

    print(f"BATCH: COMPLETE; new_attempts={submitted}")
    print("HUMAN_REVIEW: REQUIRED")
    return 0


def main(
    argv: list[str] | None = None,
    *,
    root: Path = ROOT,
) -> int:
    parser = argparse.ArgumentParser(
        description="Пакетная live-приёмка с ограничением расхода GigaChat"
    )

    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--max-items", type=int, default=2)
    args = parser.parse_args(argv)

    if not 1 <= args.max_items <= 3:
        parser.error("--max-items must be between 1 and 3")

    try:
        items = load_manifest(root)
    except (OSError, ValueError, KeyError, TypeError):
        print("MANIFEST: FAIL")
        return 1

    print(f"MANIFEST: {len(items)}/20")

    if not args.confirm_live:
        for item in items:
            print(f"DRY RUN: {item.identifier} ({item.source_scope})")
        print("NETWORK: DISABLED")
        return 0

    print("LIVE MODE: EXPLICITLY CONFIRMED")
    print("MAX LOGICAL LLM CALLS:", args.max_items * 2)

    try:
        return run_batch(items, root=root, max_items=args.max_items)
    except (OSError, ValueError, TypeError):
        print("BATCH: FAIL (local state requires inspection)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
