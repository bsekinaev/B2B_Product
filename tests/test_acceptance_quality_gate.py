"""Раздельные проверки HTTP и live-качества без внешних запросов."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.run_acceptance as acceptance


def live_row(name: str) -> dict:
    return {
        "case": name,
        "mode": "live",
        "http_status": 200,
        "status": "ready_for_review",
        "specs_unchanged": True,
        "seo_title_chars": 40,
        "seo_description_chars": 900,
        "search_queries_count": 4,
        "commercial_note_chars": 80,
        "warnings_count": 0,
        "missing_fields_count": 0,
        "editorial_review_required": True,
    }


def two_live_rows() -> list[dict]:
    return [live_row(case.name) for case in acceptance.LIVE_CASES]


@pytest.mark.parametrize(
    ("key", "bad_value", "reason"),
    [
        ("status", "requires_revision", "status_not_ready_for_review"),
        ("seo_title_chars", 0, "seo_title_length"),
        ("seo_title_chars", 71, "seo_title_length"),
        ("seo_description_chars", 799, "seo_description_length"),
        ("seo_description_chars", 1201, "seo_description_length"),
        ("search_queries_count", 2, "search_queries_count"),
        ("search_queries_count", 6, "search_queries_count"),
        ("commercial_note_chars", 0, "commercial_note_empty"),
        ("warnings_count", 1, "validation_warnings"),
        ("missing_fields_count", 1, "missing_fields"),
        ("specs_unchanged", False, "specifications_changed"),
    ],
)
def test_quality_gate_rejects_invalid_result(
    key: str,
    bad_value: object,
    reason: str,
) -> None:
    row = live_row("Тест")
    row[key] = bad_value

    assert reason in acceptance.content_quality_failures(row)


def test_valid_live_row_passes_formal_quality_gate() -> None:
    assert acceptance.content_quality_failures(live_row("Тест")) == []


def test_live_revision_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = two_live_rows()
    rows[0]["status"] = "requires_revision"

    monkeypatch.setattr(acceptance, "run_acceptance", lambda *, live: rows)

    assert acceptance.main(["--live"]) == 2

    output = capsys.readouterr().out
    assert "HTTP_CONTRACT: PASS" in output
    assert "CONTENT_QUALITY: FAIL" in output


def test_live_formal_success_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        acceptance,
        "run_acceptance",
        lambda *, live: two_live_rows(),
    )

    assert acceptance.main(["--live"]) == 0
    assert "HUMAN_REVIEW: REQUIRED" in capsys.readouterr().out


def test_live_quality_rejects_missing_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acceptance, "run_acceptance", lambda *, live: [])

    assert acceptance.main(["--live"]) == 2


def test_report_contains_quality_without_external_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = two_live_rows()
    rows[0]["status"] = "requires_revision"
    rows[0]["sdk_exception"] = "super-secret-test-value"

    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(acceptance, "run_acceptance", lambda *, live: rows)

    assert acceptance.main(["--live", "--report"]) == 2

    report_path = tmp_path / "artifacts" / "acceptance.json"
    text = report_path.read_text(encoding="utf-8")
    report = json.loads(text)

    assert report[0]["content_quality"] == "FAIL"
    assert "status_not_ready_for_review" in report[0]["quality_failures"]
    assert report[1]["content_quality"] == "PASS"
    assert "super-secret-test-value" not in text
    assert "sdk_exception" not in text


def test_offline_cli_does_not_evaluate_live_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch(
        "app.llm.client.GigaChat",
        side_effect=AssertionError("real GigaChat must not be called"),
    ):
        assert acceptance.main([]) == 0

    output = capsys.readouterr().out
    assert "HTTP_CONTRACT: PASS" in output
    assert "CONTENT_QUALITY: NOT_EVALUATED" in output


@pytest.mark.parametrize(
    "fixture",
    ["meter_dm02_series", "rosma_bt_51_211"],
)
def test_live_cases_use_submission_products(fixture: str) -> None:
    product = acceptance.load_product(fixture)
    assert product["name"]
    assert product["manufacturer"]
    assert len(product["specs"]) >= 8


def test_contract_failure_returns_exit_one_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*, live: bool) -> list[dict]:
        raise RuntimeError("super-secret-test-value")

    monkeypatch.setattr(acceptance, "run_acceptance", fail)

    assert acceptance.main(["--live"]) == 1

    output = capsys.readouterr().out
    assert "ACCEPTANCE: FAIL (RuntimeError)" in output
    assert "super-secret-test-value" not in output
