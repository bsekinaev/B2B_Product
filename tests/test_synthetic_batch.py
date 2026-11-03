"""Каждый синтетический сценарий выполняется независимо в pytest."""

import pytest

from scripts.run_synthetic_batch import build_cases, run_case


@pytest.mark.parametrize(
    "scenario",
    build_cases(),
    ids=lambda scenario: scenario.case_id,
)
def test_synthetic_product(scenario) -> None:
    record = run_case(scenario)
    assert record["passed"], f"{record['case_id']}: {record['problems']}"


def test_rich_scenarios_have_distinct_specs() -> None:
    rich = [scenario for scenario in build_cases() if scenario.group == "rich"]
    signatures = {tuple(sorted(scenario.payload["specs"].items())) for scenario in rich}

    assert len(rich) == 10
    assert len(signatures) == 10
