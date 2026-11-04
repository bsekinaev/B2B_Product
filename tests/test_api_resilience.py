"""Регрессии ошибок конфигурации и недостаточных характеристик."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.generator import generate_card
from app.main import app
from app.schemas import GenerationStatus, ProductInput


def valid_payload() -> dict:
    return {
        "name": "Манометр ТЕСТ",
        "manufacturer": "Тестовый завод",
        "specs": {"диапазон измерений": "0–1 МПа"},
        "description": "Прибор для измерения давления.",
    }


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("GIGACHAT_SCOPE", "INVALID_SCOPE"),
        ("GIGACHAT_VERIFY_SSL_CERTS", "false"),
        ("GIGACHAT_BASE_URL", "https://invalid.example/v1"),
        ("GIGACHAT_MAX_RETRIES", "99"),
    ],
)
def test_invalid_configuration_returns_safe_503(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    secret = "example-not-real-credential"
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", secret)
    monkeypatch.setenv(variable, value)

    with patch(
        "app.main.GigaChatProvider",
        side_effect=AssertionError("Provider must not be created"),
    ):
        with TestClient(app) as client:
            response = client.post("/generate", json=valid_payload())
            health = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration"}}
    assert secret not in response.text
    assert variable not in response.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


class ForbiddenProvider:
    def generate_text(self, **_kwargs: object) -> str:
        raise AssertionError("LLM called without technical facts")


@pytest.mark.parametrize("specs", [{}, {"диапазон": ""}])
def test_description_only_does_not_call_llm(
    specs: dict[str, str],
) -> None:
    product = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Тестовый завод",
        specs=specs,
        description="Прибор для измерения давления.",
    )

    result = generate_card(
        product,
        ForbiddenProvider(),  # type: ignore[arg-type]
    )

    assert result.status == GenerationStatus.INSUFFICIENT_DATA
    assert result.card.specifications == specs
    assert "specs" in result.missing_fields
    assert result.card.seo_description is None

    if "диапазон" in specs:
        assert "specs.диапазон" in result.missing_fields


def test_http_description_only_skips_llm() -> None:
    payload = valid_payload()
    payload["specs"] = {}

    with patch("app.main.GigaChatProvider", return_value=ForbiddenProvider()):
        with TestClient(app) as client:
            response = client.post("/generate", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert response.json()["card"]["specifications"] == {}
