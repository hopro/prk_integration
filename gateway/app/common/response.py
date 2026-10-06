from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def unified_ok(data: Any = None) -> JSONResponse:
    return JSONResponse(
        content={"success": True, "data": data, "error": None},
        status_code=status.HTTP_200_OK,
    )


def unified_error(code: str, message: str, http_status: int = 400) -> JSONResponse:
    return JSONResponse(
        content={"success": False, "data": None, "error": {"code": code, "message": message}},
        status_code=http_status,
    )
