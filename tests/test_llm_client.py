"""Контракт адаптера GigaChat: без сетевых запросов и реальных секретов."""

import ssl
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

import app.llm.client as llm_module
from app.config import Settings
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "gigachat_credentials": SecretStr("TEST_AUTHORIZATION_KEY"),
        "gigachat_model": "GigaChat-2",
        "gigachat_max_retries": 1,
        "gigachat_verify_ssl_certs": True,
        "gigachat_ca_bundle_file": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def completion(text: object = " Готово ", finish_reason: str | None = "stop") -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ]
    )


class FakeSDK:
    """Подмена исключительно транспортного слоя SDK."""

    def __init__(self, *, answer: object = None, exception: Exception | None = None) -> None:
        self.answer = completion() if answer is None else answer
        self.exception = exception
        self.kwargs: dict[str, Any] = {}
        self.requests: list[object] = []
        self.closed = False

    def factory(self, **kwargs: Any) -> "FakeSDK":
        self.kwargs = kwargs
        return self

    def __enter__(self) -> "FakeSDK":
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def chat(self, request: object) -> object:
        self.requests.append(request)
        if self.exception:
            raise self.exception
        return self.answer


def test_success_preserves_roles_text_and_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    text = GigaChatProvider(make_settings()).generate_text(
        system_prompt="Правила", user_prompt="Параметры манометра"
    )

    assert text == "Готово"
    assert sdk.closed is True
    assert len(sdk.requests) == 1
    request = sdk.requests[0]
    assert request.messages[0].role == llm_module.MessagesRole.SYSTEM
    assert request.messages[0].content == "Правила"
    assert request.messages[1].role == llm_module.MessagesRole.USER
    assert request.messages[1].content == "Параметры манометра"
    assert sdk.kwargs["credentials"] == "TEST_AUTHORIZATION_KEY"
    assert sdk.kwargs["model"] == "GigaChat-2"
    assert sdk.kwargs["verify_ssl_certs"] is True
    assert sdk.kwargs["max_retries"] == 1
    assert sdk.kwargs["ca_bundle_file"] is None


def test_explicit_ca_file_passed_to_sdk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ca = tmp_path / "root.crt"
    ca.write_text("fake fixture", encoding="utf-8")
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    GigaChatProvider(make_settings(gigachat_ca_bundle_file=str(ca))).generate_text(
        system_prompt="Система", user_prompt="Товар"
    )

    assert sdk.kwargs["ca_bundle_file"] == str(ca)
    assert sdk.kwargs["verify_ssl_certs"] is True


@pytest.mark.parametrize("value", [None, SecretStr(""), SecretStr("  ")])
def test_missing_credentials_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch, value: SecretStr | None
) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)
    provider = GigaChatProvider(make_settings(gigachat_credentials=value))

    with pytest.raises(LLMError) as raised:
        provider.generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == LLMErrorCode.CONFIGURATION
    assert not sdk.requests
    assert not sdk.kwargs


@pytest.mark.parametrize(
    ("system_prompt", "user_prompt"),
    [("", "Товар"), ("Роль", "   ")],
)
def test_blank_prompts_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch, system_prompt: str, user_prompt: str
) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    assert raised.value.code == LLMErrorCode.INVALID_REQUEST
    assert not sdk.requests


def test_missing_ca_file_fails_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)
    provider = GigaChatProvider(
        make_settings(gigachat_ca_bundle_file=str(tmp_path / "not-present.crt"))
    )

    with pytest.raises(LLMError) as raised:
        provider.generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == LLMErrorCode.CONFIGURATION
    assert not sdk.requests


@pytest.mark.parametrize(
    ("answer", "expected_code"),
    [
        (completion(""), LLMErrorCode.BAD_RESPONSE),
        (completion("   "), LLMErrorCode.BAD_RESPONSE),
        (completion(None), LLMErrorCode.BAD_RESPONSE),
        (completion("обрыв", finish_reason="length"), LLMErrorCode.BAD_RESPONSE),
        (completion("нет причины завершения", finish_reason=None), LLMErrorCode.BAD_RESPONSE),
        (completion("отклонён", finish_reason="blacklist"), LLMErrorCode.BAD_RESPONSE),
        (SimpleNamespace(choices=[]), LLMErrorCode.BAD_RESPONSE),
        (SimpleNamespace(choices=[SimpleNamespace(message=None)]), LLMErrorCode.BAD_RESPONSE),
        (
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="текст"))]),
            LLMErrorCode.BAD_RESPONSE,
        ),
    ],
)
def test_unusable_model_reply_rejected(
    monkeypatch: pytest.MonkeyPatch, answer: object, expected_code: LLMErrorCode
) -> None:
    sdk = FakeSDK(answer=answer)
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == expected_code
    assert sdk.closed is True


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (httpx.ConnectError("secret transport details"), LLMErrorCode.UNAVAILABLE),
        (httpx.ReadTimeout("secret timeout details"), LLMErrorCode.TIMEOUT),
    ],
)
def test_httpx_transport_and_timeout_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, code: LLMErrorCode
) -> None:
    sdk = FakeSDK(exception=failure)
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == code
    assert raised.value.retryable is True
    assert "secret" not in str(raised.value)
    assert sdk.closed is True


@pytest.mark.parametrize(
    ("exception_name", "code", "retryable"),
    [
        ("AuthenticationError", LLMErrorCode.AUTHENTICATION, False),
        ("ForbiddenError", LLMErrorCode.AUTHENTICATION, False),
        ("RateLimitError", LLMErrorCode.RATE_LIMITED, True),
        ("ServerError", LLMErrorCode.UNAVAILABLE, True),
        ("GigaChatException", LLMErrorCode.PROVIDER_REJECTED, False),
        ("BadRequestError", LLMErrorCode.INVALID_REQUEST, False),
        ("RequestEntityTooLargeError", LLMErrorCode.INVALID_REQUEST, False),
        ("UnprocessableEntityError", LLMErrorCode.INVALID_REQUEST, False),
        ("NotFoundError", LLMErrorCode.CONFIGURATION, False),
    ],
)
def test_sdk_errors_are_classified_without_exposing_details(
    monkeypatch: pytest.MonkeyPatch,
    exception_name: str,
    code: LLMErrorCode,
    retryable: bool,
) -> None:
    class SimulatedSDKError(Exception):
        pass

    monkeypatch.setattr(llm_module, exception_name, SimulatedSDKError)
    sdk = FakeSDK(exception=SimulatedSDKError("SECRET_REMOTE_ERROR"))
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "SECRET_REMOTE_ERROR" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_bad_model_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings(gigachat_model=" ")).generate_text(
            system_prompt="Роль", user_prompt="Товар"
        )

    assert raised.value.code == LLMErrorCode.CONFIGURATION
    assert not sdk.requests


def test_request_construction_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    def invalid_chat(**_: object) -> object:
        raise ValueError("SECRET_REQUEST_DATA")

    monkeypatch.setattr(llm_module, "Chat", invalid_chat)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(system_prompt="Роль", user_prompt="Товар")

    assert raised.value.code == LLMErrorCode.INVALID_REQUEST
    assert "SECRET_REQUEST_DATA" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert not sdk.requests


@pytest.mark.parametrize("invalid_prompt", [None, 123, ["текст"]])
def test_invalid_prompt_type_rejected_without_network(
    monkeypatch: pytest.MonkeyPatch, invalid_prompt: object
) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings()).generate_text(
            system_prompt=invalid_prompt,  # type: ignore[arg-type]
            user_prompt="Товар",
        )

    assert raised.value.code == LLMErrorCode.INVALID_REQUEST
    assert not sdk.requests


def test_invalid_ca_bundle_ssl_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "invalid.crt"
    bundle.write_text("not a certificate", encoding="utf-8")

    def broken_sdk(**_: object) -> object:
        raise ssl.SSLError("SECRET_CERTIFICATE_DETAILS")

    monkeypatch.setattr(llm_module, "GigaChat", broken_sdk)

    with pytest.raises(LLMError) as raised:
        GigaChatProvider(make_settings(gigachat_ca_bundle_file=str(bundle))).generate_text(
            system_prompt="Роль", user_prompt="Товар"
        )

    assert raised.value.code == LLMErrorCode.CONFIGURATION
    assert "SECRET_CERTIFICATE_DETAILS" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_structured_request_sets_response_format_and_bounded_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = FakeSDK()
    monkeypatch.setattr(llm_module, "GigaChat", sdk.factory)
    schema = {"type": "json_schema", "schema": {"type": "object"}, "strict": True}
    GigaChatProvider(make_settings()).generate_text(
        system_prompt="Правила", user_prompt="Товар", response_format=schema
    )
    request = sdk.requests[0]
    assert request.max_tokens == 1400
    assert (
        request.response_format.model_dump(mode="json", by_alias=True, exclude_none=True) == schema
    )
