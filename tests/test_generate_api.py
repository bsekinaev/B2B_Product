"""HTTP-границы /generate: сырой JSON, лимиты, ошибки и отсутствие доступа к реальному API."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.llm.client import LLMError, LLMErrorCode


class FakeProvider:
    def __init__(self, *_: object) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = json.dumps(
            {
                "seo_title": "Манометр DM 02",
                "seo_description": "Черновое описание",
                "search_queries": ["манометр DM 02", "манометр купить", "манометр Манотомь"],
                "commercial_note": "Контроль давления",
            },
            ensure_ascii=False,
        )
        self.failure: LLMError | None = None

    def generate_text(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.answer


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeProvider]:
    provider = FakeProvider()
    monkeypatch.setattr(main_module, "GigaChatProvider", lambda _: provider)
    return TestClient(main_module.app), provider


def input_product() -> dict[str, Any]:
    return {
        "name": "Манометр DM 02",
        "manufacturer": "Манотомь",
        "specs": {"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
        "description": "Прибор для измерения давления",
    }


def test_generate_success_returns_draft_and_untouched_specs(
    api: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = api
    response = client.post("/generate", json=input_product())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "requires_revision"
    assert data["card"]["specifications"] == input_product()["specs"]
    assert data["card"]["seo_title"] == "Манометр DM 02"
    assert len(provider.calls) == 1


def test_openapi_exposes_product_schema(api: tuple[TestClient, FakeProvider]) -> None:
    client, _ = api
    schema = client.get("/openapi.json").json()
    body = schema["paths"]["/generate"]["post"]["requestBody"]
    assert body["required"] is True
    assert "name" in body["content"]["application/json"]["schema"]["properties"]


def test_empty_facts_no_model_call(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    response = client.post("/generate", json={"name": "Манометр", "manufacturer": "Завод"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert not provider.calls


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ('{"name":"A", "name":"B", "manufacturer":"Z"}', "duplicate_json_key"),
        (
            '{"name":"A", "manufacturer":"Z", "specs":{"x":"1","x":"2"}}',
            "duplicate_json_key",
        ),
        ('{"name":"A", "manufacturer":"Z", "specs":{"\\u0078":"1","x":"2"}}', "duplicate_json_key"),
        ('{"name":', "invalid_json"),
        ('{"name":"A", "manufacturer":"Z", "specs":{"x":NaN}}', "invalid_json"),
        ('{"name":"A"}', "invalid_product"),
        ("[]", "invalid_product"),
    ],
)
def test_bad_json_rejected_without_model_call(
    api: tuple[TestClient, FakeProvider], raw: str, code: str
) -> None:
    client, provider = api
    response = client.post(
        "/generate", content=raw.encode("utf-8"), headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert not provider.calls


def test_invalid_unicode_rejected(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    response = client.post(
        "/generate", content=b"\xff", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_json"
    assert not provider.calls


def test_payload_over_limit_is_413(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    body = b" " * 40_000 + b"{}"
    response = client.post("/generate", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"
    assert not provider.calls


def test_normalized_size_limit_remains_in_force(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    data = input_product()
    data["specs"] = {f"поле{i}": "B" * 450 for i in range(40)}
    response = client.post("/generate", json=data)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_product"
    assert not provider.calls


def test_content_type_must_be_json(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    response = client.post("/generate", content="name=A")
    assert response.status_code == 415
    assert not provider.calls


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (LLMErrorCode.CONFIGURATION, 503),
        (LLMErrorCode.AUTHENTICATION, 503),
        (LLMErrorCode.RATE_LIMITED, 429),
        (LLMErrorCode.TIMEOUT, 504),
        (LLMErrorCode.UNAVAILABLE, 503),
        (LLMErrorCode.PROVIDER_REJECTED, 502),
        (LLMErrorCode.INVALID_REQUEST, 502),
        (LLMErrorCode.BAD_RESPONSE, 502),
    ],
)
def test_provider_errors_are_sanitized(
    api: tuple[TestClient, FakeProvider], code: LLMErrorCode, status: int
) -> None:
    client, provider = api
    provider.failure = LLMError(code)
    response = client.post("/generate", json=input_product())
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code.value}}
    assert "GIGACHAT_CREDENTIALS" not in response.text


def test_model_invalid_json_is_revision_not_http_500(api: tuple[TestClient, FakeProvider]) -> None:
    client, provider = api
    provider.answer = "not-json"
    response = client.post("/generate", json=input_product())
    assert response.status_code == 200
    assert response.json()["status"] == "requires_revision"
    assert response.json()["card"]["specifications"] == input_product()["specs"]


def test_http_generate_ready_for_manual_review_only_after_validation(
    api: tuple[TestClient, FakeProvider],
) -> None:
    client, provider = api
    phrase = "Манометр предназначен для измерения избыточного давления; "
    provider.answer = json.dumps(
        {
            "seo_title": "Манометр DM 02 — характеристики",
            "seo_description": (phrase * 20)[:850],
            "search_queries": ["манометр DM 02", "манометр Манотомь", "манометр 0–1,6 МПа"],
            "commercial_note": "Для контроля избыточного давления",
        },
        ensure_ascii=False,
    )
    response = client.post("/generate", json=input_product())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready_for_review"
    assert data["warnings"] == []
    assert data["card"]["specifications"] == input_product()["specs"]


def test_http_generate_short_description_requires_revision(
    api: tuple[TestClient, FakeProvider],
) -> None:
    client, _ = api
    response = client.post("/generate", json=input_product())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "requires_revision"
    assert any("SEO-описание" in warning for warning in data["warnings"])


def test_http_generate_description_only_is_insufficient_data(
    api: tuple[TestClient, FakeProvider],
) -> None:
    client, _ = api
    request = {"name": "Манометр", "manufacturer": "Завод", "description": "Измерение давления"}
    response = client.post("/generate", json=request)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "insufficient_data"
    assert "specs" in data["missing_fields"]
    assert data["card"]["specifications"] == {}
