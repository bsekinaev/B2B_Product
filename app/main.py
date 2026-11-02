"""Точка входа HTTP API."""

from fastapi import FastAPI

app = FastAPI(
    title="B2B Product Content Generator",
    description="Подготовка черновиков карточек технических товаров.",
    version="0.1.0",
)


@app.get("/health", tags=["Сервис"])
def health() -> dict[str, str]:
    """Проверить работоспособность HTTP API."""
    return {"status": "ok"}
