"""Настройки приложения и подключения к GigaChat API."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения и локального .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gigachat_credentials: SecretStr | None = None

    gigachat_scope: Literal[
        "GIGACHAT_API_PERS",
        "GIGACHAT_API_B2B",
        "GIGACHAT_API_CORP",
    ] = "GIGACHAT_API_PERS"

    gigachat_model: str = "GigaChat-2"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_max_output_tokens: int = Field(default=1400, ge=512, le=4096)

    gigachat_timeout: float = Field(
        default=30.0,
        gt=0,
        le=120,
    )

    gigachat_max_retries: int = Field(
        default=1,
        ge=0,
        le=2,
    )

    gigachat_verify_ssl_certs: bool = True
    gigachat_ca_bundle_file: str | None = None

    @field_validator("gigachat_verify_ssl_certs")
    @classmethod
    def ensure_tls_verification(cls, value: bool) -> bool:
        """Не допускать отключения проверки TLS-сертификатов."""
        if not value:
            raise ValueError("TLS certificate verification must remain enabled")
        return value

    @field_validator("gigachat_base_url")
    @classmethod
    def require_official_gigachat_url(cls, value: str) -> str:
        """Не передавать Authorization key на произвольный HTTP(S)-сервер."""
        if value != "https://api.giga.chat/v1":
            raise ValueError("Use the official GigaChat HTTPS v1 API endpoint")
        return value
