"""Точка входа HTTP API."""

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.generator import generate_card
from app.http_input import read_product_request
from app.llm.client import GigaChatProvider, LLMError, LLMErrorCode
from app.schemas import GenerationResult, ProductInput

app = FastAPI(
    title="B2B Product Content Generator",
    description="Подготовка черновиков карточек технических товаров.",
    version="0.1.0",
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
        return await run_in_threadpool(generate_card, product, GigaChatProvider(Settings()))
    except LLMError as error:
        raise HTTPException(
            status_code=ERROR_HTTP_STATUS[error.code],
            detail={"code": error.code.value},
        ) from None
