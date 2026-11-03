"""Ограниченный приём JSON без потери дублирующихся технических фактов."""

import json

from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.generator import DuplicateJSONKey, reject_json_constant, unique_json_keys
from app.schemas import ProductInput

MAX_REQUEST_BODY_BYTES = 32_768


async def read_product_request(request: Request) -> ProductInput:
    """Ограничить фактический поток байтов до JSON-декодирования и Pydantic."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail={"code": "unsupported_media_type"})

    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdecimal():
        if len(declared_length) > 10 or int(declared_length) > MAX_REQUEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail={"code": "request_too_large"})

    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > MAX_REQUEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail={"code": "request_too_large"})
        payload.extend(chunk)

    try:
        data = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_json_keys,
            parse_constant=reject_json_constant,
        )
    except DuplicateJSONKey:
        raise HTTPException(status_code=422, detail={"code": "duplicate_json_key"}) from None
    except (UnicodeError, ValueError, TypeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_json"}) from None

    try:
        return ProductInput.model_validate(data)
    except ValidationError:
        # Не возвращать входные values (в том числе возможные секреты) в 422.
        raise HTTPException(status_code=422, detail={"code": "invalid_product"}) from None
