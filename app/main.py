"""Точка входа HTTP API."""

from importlib.metadata import version as package_version
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.generator import generate_card
from app.http_input import read_product_request
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode
from app.schemas import GenerationResult, ProductInput

app = FastAPI(
    title="Генератор B2B-карточек товаров",
    description="Подготовка черновиков карточек технических товаров.",
    version=package_version("b2b-product-content-generator"),
)


@app.get("/health", tags=["Сервис"])
def health() -> dict[str, str]:
    """Проверить работоспособность HTTP API."""
    return {"status": "ok"}


ERROR_HTTP_STATUS = {
    LLMErrorCode.CONFIGURATION: 503,
    LLMErrorCode.INVALID_REQUEST: 502,
    LLMErrorCode.AUTHENTICATION: 503,
    LLMErrorCode.RATE_LIMITED: 429,
    LLMErrorCode.TIMEOUT: 504,
    LLMErrorCode.UNAVAILABLE: 503,
    LLMErrorCode.PROVIDER_REJECTED: 502,
    LLMErrorCode.BAD_RESPONSE: 502,
}


# Один активный запрос к GigaChat в процессе — безопасная настройка для
# GIGACHAT_API_PERS. Разрешённые B2B-потоки требуют отдельной конфигурации.
# Важно: это процесс-локальный ограничитель, не распределённый между worker'ами.
_GIGACHAT_PERMIT = BoundedSemaphore(value=1)
_QUEUE_WAIT_SECONDS = 120.0


def _generate_with_provider_slot(product: ProductInput, settings: Settings) -> GenerationResult:
    """Удерживать слот на протяжении всех логических LLM-вызовов карточки."""
    if not _GIGACHAT_PERMIT.acquire(timeout=_QUEUE_WAIT_SECONDS):
        raise LLMError(LLMErrorCode.RATE_LIMITED, retryable=True)
    try:
        return generate_card(product, GigaChatProvider(settings))
    finally:
        _GIGACHAT_PERMIT.release()


@app.post(
    "/generate",
    response_model=GenerationResult,
    tags=["Генерация"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ProductInput.model_json_schema()}},
        }
    },
)
async def generate(request: Request) -> GenerationResult:
    """Создать черновик; синхронный SDK запускается в отдельном потоке."""
    product = await read_product_request(request)

    try:
        settings = Settings()
    except (ValidationError, SettingsError):
        raise HTTPException(
            status_code=503,
            detail={"code": LLMErrorCode.CONFIGURATION.value},
        ) from None

    try:
        return await run_in_threadpool(_generate_with_provider_slot, product, settings)
    except LLMError as error:
        raise HTTPException(
            status_code=ERROR_HTTP_STATUS[error.code],
            detail={"code": error.code.value},
        ) from None
