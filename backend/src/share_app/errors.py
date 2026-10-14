"""API errors: always JSON `{"error": code, "message": English text, ...numbers}`.

The frontend shows its own translated text by `error`; numbers the text depends on are
sent as separate fields. `message` is for debugging and third-party clients.
"""

from __future__ import annotations

from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, headers: dict[str, str] | None = None,
                 **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.extra = extra


def not_found(message: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", message)


def too_many_attempts() -> ApiError:
    return ApiError(429, "too_many_attempts", "Too many attempts. Try again in 15 minutes", retry_after=900)


async def json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        raise ApiError(400, "bad_json", "Expected JSON") from None
    if not isinstance(data, dict):
        raise ApiError(400, "bad_json", "Expected a JSON object")
    return data


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    body = {"error": exc.code, "message": exc.message, **exc.extra}
    return JSONResponse(body, status_code=exc.status, headers=exc.headers)


HTTP_MESSAGES = {
    404: ("not_found", "Not found"),
    405: ("method_not_allowed", "Method not allowed"),
}


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code, message = HTTP_MESSAGES.get(exc.status_code, ("http_error", str(exc.detail)))
    return JSONResponse({"error": code, "message": message}, status_code=exc.status_code,
                        headers=dict(exc.headers or {}))
