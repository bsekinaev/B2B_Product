"""Тесты конфигурации приложения."""

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_gigachat_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Изолировать тесты от локальных реквизитов GigaChat."""
    variables = [
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_SCOPE",
        "GIGACHAT_MODEL",
        "GIGACHAT_BASE_URL",
        "GIGACHAT_TIMEOUT",
        "GIGACHAT_MAX_RETRIES",
        "GIGACHAT_VERIFY_SSL_CERTS",
        "GIGACHAT_CA_BUNDLE_FILE",
    ]

    for variable in variables:
        monkeypatch.delenv(variable, raising=False)


def test_default_settings() -> None:
    """Настройки по умолчанию должны быть безопасными."""
    settings = Settings(_env_file=None)

    assert settings.gigachat_credentials is None
    assert settings.gigachat_verify_ssl_certs is True
    assert settings.gigachat_timeout == 30.0
    assert settings.gigachat_max_retries == 1


def test_credentials_hidden_in_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Секрет не должен появляться в repr конфигурации."""
    fake_credential = "fake-test-credential-only"

    monkeypatch.setenv(
        "GIGACHAT_CREDENTIALS",
        fake_credential,
    )

    settings = Settings(_env_file=None)

    assert settings.gigachat_credentials is not None
    assert settings.gigachat_credentials.get_secret_value() == fake_credential
    assert fake_credential not in repr(settings)


def test_ssl_verification_cannot_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Приложение должно запрещать отключение TLS-проверки."""
    monkeypatch.setenv("GIGACHAT_VERIFY_SSL_CERTS", "false")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_ssl_verification_enabled_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Значение 'true' из .env принимается как включённая TLS-проверка."""
    monkeypatch.setenv("GIGACHAT_VERIFY_SSL_CERTS", "true")

    settings = Settings(_env_file=None)

    assert settings.gigachat_verify_ssl_certs is True


def test_timeout_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Таймаут не может быть нулевым."""
    monkeypatch.setenv("GIGACHAT_TIMEOUT", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_scope_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неизвестный scope должен отклоняться."""
    monkeypatch.setenv("GIGACHAT_SCOPE", "INVALID_SCOPE")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_retry_limit_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Количество повторных попыток ограничено."""
    monkeypatch.setenv("GIGACHAT_MAX_RETRIES", "100")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
