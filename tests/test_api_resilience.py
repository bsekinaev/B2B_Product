"""Регрессии для недопустимой конфигурации и отсутствующих технических фактов."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.generator import generate_card
from app.main import app
from app.schemas import GenerationStatus, ProductInput


def product_json() -> dict:
    return {
        "name": "Манометр ТЕСТ",
        "manufacturer": "Тестовый завод",
        "specs": {"диапазон": "0–1 МПа"},
        "description": "Прибор для измерения давления.",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GIGACHAT_SCOPE", "INVALID_SCOPE"),
        ("GIGACHAT_VERIFY_SSL_CERTS", "false"),
        ("GIGACHAT_BASE_URL", "https://unknown.example/v1"),
        ("GIGACHAT_MAX_RETRIES", "99"),
    ],
)
def test_invalid_settings_produce_safe_503(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "fake-secret-credential-123")

    with patch("app.main.GigaChatProvider", side_effect=AssertionError("provider used")):
        with TestClient(app) as client:
            response = client.post("/generate", json=product_json())
            health = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration"}}
    assert "fake-secret-credential-123" not in response.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


class ForbiddenProvider:
    def generate_text(self, **_kwargs: object) -> str:
        raise AssertionError("LLM must not be called without specs")


@pytest.mark.parametrize("specs", [{}, {"диапазон": ""}])
def test_description_without_any_spec_skips_llm(specs: dict[str, str]) -> None:
    product = ProductInput(
        name="Манометр ТЕСТ",
        manufacturer="Тестовый завод",
        description="Предназначен для измерения давления.",
        specs=specs,
    )

    result = generate_card(product, ForbiddenProvider())  # type: ignore[arg-type]

    assert result.status == GenerationStatus.INSUFFICIENT_DATA
    assert result.card.specifications == specs
    assert "specs" in result.missing_fields
    assert result.card.seo_description is None


def test_http_description_only_skips_llm() -> None:
    payload = product_json()
    payload["specs"] = {}

    with patch("app.main.GigaChatProvider", return_value=ForbiddenProvider()):
        with TestClient(app) as client:
            response = client.post("/generate", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert response.json()["card"]["specifications"] == {}
