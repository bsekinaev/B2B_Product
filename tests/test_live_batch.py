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


def test_real_manifest_has_twenty_distinct_models() -> None:
    entries = load_manifest(ROOT)
    assert len(entries) == 20
    assert len({entry.identifier for entry in entries}) == 20
    assert {"meter_dm02_series", "rosma_bt_51_211"}.issubset(
        {entry.identifier for entry in entries}
    )


def test_catalog_inputs_have_sufficient_specs_and_sources() -> None:
    entries = load_manifest(ROOT)

    assert all(len(entry.product.specs) >= 8 for entry in entries)
    assert all(entry.catalog_reference.startswith("https://") for entry in entries)
    assert all(entry.source_scope in {"series", "configured_variant"} for entry in entries)


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


def test_optional_rs485_is_not_claimed_for_all_variants() -> None:
    items = {item.identifier: item for item in load_manifest(ROOT)}

    for identifier in ("owen_2trm0", "owen_trm1", "owen_2trm1", "owen_trm10", "owen_trm12"):
        value = items[identifier].product.specs["интерфейс связи"]
        assert value == "RS-485, зависит от исполнения"


def test_retry_preserves_original_and_saves_second_attempt(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    items = load_manifest(root)

    assert (
        run_batch(
            items,
            root=root,
            provider_factory=lambda _settings: FakeProvider(short=True),
        )
        == 2
    )

    directory = root / "artifacts/live_batch"
    original = directory / "sample_meter.json"
    preserved = original.read_bytes()

    assert (
        run_batch(
            items,
            root=root,
            max_items=1,
            retry_id="sample_meter",
            provider_factory=lambda _settings: FakeProvider(),
        )
        == 0
    )

    second = directory / "sample_meter.attempt-002.json"
    started = directory / "sample_meter.attempt-002.started.json"

    assert original.read_bytes() == preserved
    assert started.is_file()

    record = json.loads(second.read_text(encoding="utf-8"))

    assert record["attempt_number"] == 2
    assert record["previous_attempt_file"] == "sample_meter.json"
    assert record["content_quality"] == "PASS"

    with pytest.raises(ValueError, match="already exists"):
        run_batch(
            items,
            root=root,
            max_items=1,
            retry_id="sample_meter",
        )


def test_retry_rejects_successful_original(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    items = load_manifest(root)

    assert (
        run_batch(
            items,
            root=root,
            provider_factory=lambda _settings: FakeProvider(),
        )
        == 0
    )

    with pytest.raises(ValueError, match="failed original"):
        run_batch(
            items,
            root=root,
            max_items=1,
            retry_id="sample_meter",
        )


def test_retry_rejects_changed_input(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    items = load_manifest(root)

    assert (
        run_batch(
            items,
            root=root,
            provider_factory=lambda _settings: FakeProvider(short=True),
        )
        == 2
    )

    path = root / "examples/live_batch/products/sample_meter.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["description"] = "Уточнённое назначение."
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )

    changed_items = load_manifest(root)

    with pytest.raises(ValueError, match="changed"):
        run_batch(
            changed_items,
            root=root,
            max_items=1,
            retry_id="sample_meter",
        )


def test_retry_rejects_missing_original(tmp_path: Path) -> None:
    root = make_root(tmp_path)

    with pytest.raises(ValueError, match="missing"):
        run_batch(
            load_manifest(root),
            root=root,
            max_items=1,
            retry_id="sample_meter",
        )


def test_retry_requires_one_item_limit(tmp_path: Path) -> None:
    root = make_root(tmp_path)

    with pytest.raises(ValueError, match="max_items=1"):
        run_batch(
            load_manifest(root),
            root=root,
            max_items=2,
            retry_id="sample_meter",
        )


def test_retry_preview_does_not_use_network(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_root(tmp_path)
    items = load_manifest(root)

    assert (
        run_batch(
            items,
            root=root,
            provider_factory=lambda _settings: FakeProvider(short=True),
        )
        == 2
    )

    assert (
        main(
            ["--retry-id", "sample_meter", "--max-items", "1"],
            root=root,
        )
        == 0
    )

    assert "NETWORK: DISABLED" in capsys.readouterr().out

    directory = root / "artifacts/live_batch"
    assert not (directory / "sample_meter.attempt-002.json").exists()
    assert not (directory / "sample_meter.attempt-002.started.json").exists()


@pytest.mark.parametrize(
    "identifier",
    ["owen_2trm1", "owen_trm10", "owen_trm12"],
)
def test_new_owen_products_separate_mounting_types(
    identifier: str,
) -> None:
    items = {item.identifier: item for item in load_manifest(ROOT)}
    specs = items[identifier].product.specs

    assert specs["исполнения корпуса"] == (
        "щитовой Щ1 / Щ2 / Щ5 / настенный Н / DIN-реечный Д, варианты серии"
    )
    assert specs["интерфейс связи"] == ("RS-485, зависит от исполнения")


def test_owen_2trm1_describes_output_types() -> None:
    items = {item.identifier: item for item in load_manifest(ROOT)}
    specs = items["owen_2trm1"].product.specs

    assert "типы выходных устройств" in specs
    assert specs["количество выходных устройств"] == "2"
    assert "выходные устройства" not in specs
