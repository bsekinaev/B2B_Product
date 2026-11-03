"""Экспорт полных примеров без реальной сети и API-ключей."""

import json
import sys
from pathlib import Path

import pytest

from app.schemas import GenerationResult, GenerationStatus, ProductCard
from scripts.export_live_examples import ExampleExportError, export_live_examples, main
from scripts.run_acceptance import load_product


class FakeResponse:
    def __init__(self, name: str, *, status_code: int = 200, tamper: bool = False):
        self.status_code = status_code
        product = load_product(name)
        specs = dict(product["specs"])
        if tamper:
            specs["неизвестный параметр"] = "неподтверждённое значение"
        self.content = GenerationResult(
            status=GenerationStatus.REQUIRES_REVISION,
            card=ProductCard(
                seo_title=product["name"],
                seo_description="Краткий пример без выдуманных свойств",
                specifications=specs,
                search_queries=["пример запроса"],
                commercial_note="Требуется проверка менеджера",
            ),
            warnings=["SEO-описание короче нормы"],
        ).model_dump(mode="json")

    def json(self) -> dict:
        return self.content


class FakeClient:
    def __init__(self, _app: object, *, fail_index: int | None = None, tamper=False):
        self.calls = 0
        self.fail_index = fail_index
        self.tamper = tamper

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, path: str, *, json: dict):
        assert path == "/generate"
        self.calls += 1
        name = "manometer" if self.calls == 1 else "thermometer"
        assert json == load_product(name)
        return FakeResponse(
            name,
            status_code=502 if self.fail_index == self.calls else 200,
            tamper=self.tamper,
        )


def test_export_writes_two_explicitly_unreviewed_results(tmp_path: Path) -> None:
    output = tmp_path / "examples" / "results"
    paths = export_live_examples(output_dir=output, client_factory=FakeClient)
    assert [path.name for path in paths] == ["manometer.live.json", "thermometer.live.json"]
    for path in paths:
        item = json.loads(path.read_text(encoding="utf-8"))
        assert item["source"] == "live_gigachat_api"
        assert item["review_status"] == "human_review_required"
        assert item["result"]["status"] == "requires_revision"
        assert item["result"]["card"]["specifications"] == item["product"]["specs"]


def test_refuses_to_overwrite_even_one_existing_result(tmp_path: Path) -> None:
    path = tmp_path / "manometer.live.json"
    path.write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(ExampleExportError, match="уже существуют"):
        export_live_examples(output_dir=tmp_path, client_factory=FakeClient)
    assert path.read_text(encoding="utf-8") == "do not overwrite"
    assert not (tmp_path / "thermometer.live.json").exists()


def test_http_failure_does_not_leave_partial_examples(tmp_path: Path) -> None:
    class FailingClient(FakeClient):
        def __init__(self, app: object):
            super().__init__(app, fail_index=2)

    with pytest.raises(ExampleExportError, match="HTTP 502"):
        export_live_examples(output_dir=tmp_path, client_factory=FailingClient)
    assert list(tmp_path.glob("*.json")) == []


def test_specification_tampering_aborts_export(tmp_path: Path) -> None:
    class TamperedClient(FakeClient):
        def __init__(self, app: object):
            super().__init__(app, tamper=True)

    with pytest.raises(ExampleExportError, match="характеристики изменены"):
        export_live_examples(output_dir=tmp_path, client_factory=TamperedClient)
    assert list(tmp_path.glob("*.json")) == []


def test_cli_requires_explicit_live_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["export_live_examples"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
