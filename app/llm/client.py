"""Изолированный адаптер GigaChat SDK с безопасной классификацией ошибок."""

import ssl
from enum import StrEnum
from json import JSONDecodeError
from pathlib import Path

import httpx
from gigachat import GigaChat
from gigachat.exceptions import (
    AuthenticationError,
    BadRequestError,
    ForbiddenError,
    GigaChatException,
    NotFoundError,
    RateLimitError,
    RequestEntityTooLargeError,
    ServerError,
    UnprocessableEntityError,
)
from gigachat.models import Chat, Messages, MessagesRole
from pydantic import ValidationError

from app.config import Settings


class LLMErrorCode(StrEnum):
    """Стабильные коды ошибок, не зависящие от текста ответа SDK."""

    CONFIGURATION = "configuration"
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    BAD_RESPONSE = "bad_response"


class LLMError(RuntimeError):
    """Безопасная ошибка провайдера: исключения SDK и секреты не передаются клиенту."""

    def __init__(self, code: LLMErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(f"GigaChat request failed: {code.value}")


class GigaChatProvider:
    """Генерация текста через SDK; промпты и бизнес-валидация вне адаптера."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        """Получить непустой текст ответа, не раскрывая детали ошибок SDK."""
        if (
            not isinstance(system_prompt, str)
            or not isinstance(user_prompt, str)
            or not system_prompt.strip()
            or not user_prompt.strip()
        ):
            raise LLMError(LLMErrorCode.INVALID_REQUEST)

        settings = self.settings
        credentials = settings.gigachat_credentials
        if credentials is None or not credentials.get_secret_value().strip():
            raise LLMError(LLMErrorCode.CONFIGURATION)
        if not settings.gigachat_model.strip():
            raise LLMError(LLMErrorCode.CONFIGURATION)

        ca_bundle = settings.gigachat_ca_bundle_file
        if ca_bundle and not Path(ca_bundle).is_file():
            raise LLMError(LLMErrorCode.CONFIGURATION)

        try:
            request = Chat(
                messages=[
                    Messages(role=MessagesRole.SYSTEM, content=system_prompt),
                    Messages(role=MessagesRole.USER, content=user_prompt),
                ],
                temperature=0.2,
            )
        except (ValidationError, TypeError, ValueError):
            raise LLMError(LLMErrorCode.INVALID_REQUEST) from None

        try:
            with GigaChat(
                credentials=credentials.get_secret_value(),
                scope=settings.gigachat_scope,
                model=settings.gigachat_model,
                base_url=settings.gigachat_base_url,
                verify_ssl_certs=settings.gigachat_verify_ssl_certs,
                ca_bundle_file=ca_bundle,
                timeout=settings.gigachat_timeout,
                max_retries=settings.gigachat_max_retries,
            ) as client:
                response = client.chat(request)
        except (BadRequestError, RequestEntityTooLargeError, UnprocessableEntityError):
            raise LLMError(LLMErrorCode.INVALID_REQUEST) from None
        except NotFoundError:
            raise LLMError(LLMErrorCode.CONFIGURATION) from None
        except (AuthenticationError, ForbiddenError):
            raise LLMError(LLMErrorCode.AUTHENTICATION) from None
        except RateLimitError:
            raise LLMError(LLMErrorCode.RATE_LIMITED, retryable=True) from None
        except ServerError:
            raise LLMError(LLMErrorCode.UNAVAILABLE, retryable=True) from None
        except httpx.TimeoutException:
            raise LLMError(LLMErrorCode.TIMEOUT, retryable=True) from None
        except httpx.TransportError:
            raise LLMError(LLMErrorCode.UNAVAILABLE, retryable=True) from None
        except ssl.SSLError:
            code = LLMErrorCode.CONFIGURATION if ca_bundle else LLMErrorCode.UNAVAILABLE
            raise LLMError(code) from None
        except GigaChatException:
            raise LLMError(LLMErrorCode.PROVIDER_REJECTED) from None
        except (ValidationError, JSONDecodeError):
            raise LLMError(LLMErrorCode.BAD_RESPONSE) from None

        try:
            choice = response.choices[0]
            text = choice.message.content
            finish_reason = getattr(choice.finish_reason, "value", choice.finish_reason)
        except (AttributeError, IndexError, TypeError):
            raise LLMError(LLMErrorCode.BAD_RESPONSE) from None

        if finish_reason != "stop" or not isinstance(text, str) or not text.strip():
            raise LLMError(LLMErrorCode.BAD_RESPONSE)
        return text.strip()
