"""Контракт версии OpenAPI и установленного пакета."""

from importlib.metadata import version

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_version_matches_installed_distribution() -> None:
    expected = version("b2b-product-content-generator")
    assert app.version == expected

    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == expected
