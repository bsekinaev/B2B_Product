"""Проверки одновременных HTTP-запросов и защиты квоты GigaChat без сети."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.main as api
from app.llm.client import LLMError, LLMErrorCode
from app.schemas import GenerationResult, GenerationStatus, ProductCard, ProductInput


def test_ten_simultaneous_http_calls_use_single_provider_slot() -> None:
    barrier = Barrier(10, timeout=15)
    lock = Lock()
    active = 0
    peak = 0
    calls = 0
    result = GenerationResult(
        status=GenerationStatus.READY_FOR_REVIEW,
        card=ProductCard(specifications={"тип": "термометр"}),
    )

    def fake_generate(_product: ProductInput, _provider: object) -> GenerationResult:
        nonlocal active, peak, calls
        with lock:
            active += 1
            calls += 1
            peak = max(active, peak)
        try:
            time.sleep(0.025)
            return result
        finally:
            with lock:
                active -= 1

    def worker(index: int) -> int:
        with TestClient(api.app) as client:
            barrier.wait()
            response = client.post(
                "/generate",
                json={
                    "name": f"Термометр {index}",
                    "manufacturer": "Тест",
                    "specs": {"тип": "термометр"},
                },
            )
            return response.status_code

    with (
        patch.object(api, "GigaChatProvider", lambda _settings: object()),
        patch.object(api, "generate_card", fake_generate),
        ThreadPoolExecutor(max_workers=10) as pool,
    ):
        statuses = list(pool.map(worker, range(10)))

    assert statuses == [200] * 10
    assert calls == 10
    assert peak == 1
    assert active == 0


def test_exhausted_queue_returns_safe_429_without_invoking_provider() -> None:
    item = ProductInput(name="Термометр", manufacturer="Тест", specs={"тип": "термометр"})
    assert api._GIGACHAT_PERMIT.acquire(timeout=1)
    try:
        with (
            patch.object(api, "_QUEUE_WAIT_SECONDS", 0.001),
            patch.object(api, "GigaChatProvider") as provider,
            pytest.raises(LLMError) as raised,
        ):
            api._generate_with_provider_slot(item, object())  # type: ignore[arg-type]
        assert raised.value.code == LLMErrorCode.RATE_LIMITED
        provider.assert_not_called()
    finally:
        api._GIGACHAT_PERMIT.release()


def test_provider_slot_released_after_llm_error() -> None:
    item = ProductInput(name="Термометр", manufacturer="Тест", specs={"тип": "термометр"})
    with (
        patch.object(api, "GigaChatProvider", lambda _settings: object()),
        patch.object(
            api,
            "generate_card",
            side_effect=LLMError(LLMErrorCode.UNAVAILABLE, retryable=True),
        ),
        pytest.raises(LLMError),
    ):
        api._generate_with_provider_slot(item, object())  # type: ignore[arg-type]

    expected = GenerationResult(
        status=GenerationStatus.REQUIRES_REVISION,
        card=ProductCard(specifications=item.specs),
    )
    with (
        patch.object(api, "GigaChatProvider", lambda _settings: object()),
        patch.object(api, "generate_card", return_value=expected),
    ):
        actual = api._generate_with_provider_slot(item, object())  # type: ignore[arg-type]

    assert actual == expected
