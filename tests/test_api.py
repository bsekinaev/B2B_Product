"""Тесты базовых HTTP-маршрутов."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_http_200() -> None:
    """Health endpoint должен отвечать HTTP 200."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_json() -> None:
    """Ответ health endpoint должен быть JSON."""
    response = client.get("/health")

    assert response.headers["content-type"] == "application/json"


def test_health_without_gigachat_credentials(monkeypatch) -> None:
    """Health endpoint не зависит от авторизации GigaChat."""
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_available() -> None:
    """FastAPI должен предоставлять OpenAPI-схему."""
    response = client.get("/openapi.json")

    assert response.status_code == 200

    schema = response.json()

    assert schema["info"]["title"] == "B2B Product Content Generator"
    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]
