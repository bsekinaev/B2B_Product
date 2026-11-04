"""Проверки batch runner без реального GigaChat."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.run_live_batch import (
    ROOT,
    load_manifest,
    main,
    run_batch,
)


def make_root(path: Path) -> Path:
    directory = path / "examples/live_batch"
    products = directory / "products"

    products.mkdir(parents=True)

    payload = {
        "name": "Манометр ТЕСТ",
        "manufacturer": "Тестовый завод",
        "specs": {
            "тип": "манометр",
            "диапазон": "0–10 МПа",
            "диаметр корпуса": "100 мм",
            "класс точности": "1,5",
        },
        "description": None,
    }

    (products / "sample_meter.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "goal": 20,
        "items": [
            {
                "id": "sample_meter",
                "input_file": "examples/live_batch/products/sample_meter.json",
                "catalog_reference": "https://example.com/catalog/sample",
                "source_scope": "configured_variant",
            }
        ],
    }

    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    return path


class FakeProvider:
    def __init__(self, short: bool = False):
        self.short = short

    def generate_text(self, **_kwargs: object) -> str:
        description = (
            "Краткий текст"
            if self.short
            else ("Манометр предназначен для контроля давления; " * 30)[:850]
        )

        return json.dumps(
            {
                "seo_title": "Манометр ТЕСТ",
                "seo_description": description,
                "search_queries": [
                    "Манометр ТЕСТ",
                    "Манометр ТЕСТ характеристики",
                    "Манометр ТЕСТ параметры",
                ],
                "commercial_note": "Подбор по исходным характеристикам.",
            },
            ensure_ascii=False,
        )


def test_real_manifest_has_two_initial_catalog_entries() -> None:
    entries = load_manifest(ROOT)
    assert len(entries) == 2
    assert {entry.identifier for entry in entries} == {
        "meter_dm02_series",
        "rosma_bt_51_211",
    }


def test_dry_run_does_not_create_results(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)

    assert main([], root=root) == 0
    assert "NETWORK: DISABLED" in capsys.readouterr().out
    assert not (root / "artifacts").exists()


def test_successful_attempt_is_saved_and_not_repeated(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    entries = load_manifest(root)

    assert (
        run_batch(
            entries,
            root=root,
            client_factory=TestClient,
            provider_factory=lambda _settings: FakeProvider(),
        )
        == 0
    )

    path = root / "artifacts/live_batch/sample_meter.json"
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["content_quality"] == "PASS"
    assert record["result"]["status"] == "ready_for_review"
    assert record["llm_calls"] == 1
    assert record["model_seo_text_retained"] is True

    def forbidden(_settings: object) -> None:
        raise AssertionError("Second invocation must not use LLM")

    assert (
        run_batch(
            entries,
            root=root,
            provider_factory=forbidden,
        )
        == 0
    )

    assert json.loads(path.read_text(encoding="utf-8")) == record


def test_failed_quality_is_recorded_without_retries(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    entries = load_manifest(root)

    code = run_batch(
        entries,
        root=root,
        provider_factory=lambda _settings: FakeProvider(short=True),
    )

    assert code == 2

    path = root / "artifacts/live_batch/sample_meter.json"
    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["content_quality"] == "FAIL"
    assert "status_not_ready_for_review" in record["quality_failures"]
    assert record["llm_calls"] == 1


def test_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    path = root / "examples/live_batch/manifest.json"

    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"].append(dict(data["items"][0]))

    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate"):
        load_manifest(root)
