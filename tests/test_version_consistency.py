"""Согласованность версии пакета, pyproject.toml и HTTP OpenAPI."""

import tomllib
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_project_package_and_openapi_versions_match() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    expected = project["project"]["version"]
    installed = version("b2b-product-content-generator")

    assert installed == expected
    assert app.version == expected

    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == expected
