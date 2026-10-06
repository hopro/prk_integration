import os
import logging
from typing import Any

import httpx

from app.services import settings_db

logger = logging.getLogger(__name__)

# Адрес шлюза и учётные данные задаются переменными окружения. Значения по
# умолчанию намеренно пустые: пароль в коде — это утечка, а не удобство.
MIS_GATEWAY_URL = os.getenv("MIS_GATEWAY_URL", "http://localhost:8010")
GATEWAY_LOGIN = os.getenv("GATEWAY_LOGIN", "")
GATEWAY_PASSWORD = os.getenv("GATEWAY_PASSWORD", "")

_token: str | None = None


def invalidate_token():
    global _token
    _token = None


async def _login() -> str:
    global _token
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        resp = await client.post(
            f"{MIS_GATEWAY_URL}/api/v1/auth/login",
            json={"login": GATEWAY_LOGIN, "password": GATEWAY_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
        _token = data.get("access_token") or data.get("data", {}).get("access_token")
        if not _token:
            raise RuntimeError(f"Login failed: {data}")
        logger.info("MIS gateway login OK")
        return _token


def _body_excerpt(text: str, limit: int = 300) -> str:
    """Короткое читаемое тело ответа шлюза для сообщения об ошибке."""
    flat = " ".join((text or "").split())
    return flat[:limit] if flat else "(пусто)"


def _gateway_error(result: Any) -> str:
    """Сообщение об ошибке из ответа шлюза.

    Раньше здесь мог получиться пустой текст, если шлюз присылал
    {"success": false, "error": null} — пользователь видел
    «Шлюз не принял адрес ЕЦП: » без объяснения. Теперь подставляется
    код ошибки, а при его отсутствии — всё тело ответа.
    """
    if not isinstance(result, dict):
        return _body_excerpt(str(result))

    error = result.get("error")
    if isinstance(error, dict):
        message = (error.get("message") or "").strip()
        code = (error.get("code") or "").strip()
        if message and code:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return f"ошибка шлюза {code}"
    elif isinstance(error, str) and error.strip():
        return error.strip()
    elif error is None:
        return f"шлюз не вернул описание ошибки (тело: {_body_excerpt(str(result))})"

    return _body_excerpt(str(result))


async def _get_token() -> str:
    global _token
    if _token:
        return _token
    return await _login()


async def _request(method: str, path: str, **kwargs) -> dict[str, Any]:
    global _token
    token = await _get_token()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        resp = await client.request(method, f"{MIS_GATEWAY_URL}{path}", headers=headers, **kwargs)

    if resp.status_code == 401:
        token = await _login()
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            resp = await client.request(method, f"{MIS_GATEWAY_URL}{path}", headers=headers, **kwargs)

    # Тело 502-ответа возвращаем как есть: так сообщение об ошибке от ЕЦП
    # доходит до пользователя, а не теряется внутри raise_for_status.
    if resp.status_code == 502:
        try:
            return resp.json()
        except Exception:
            pass

    if resp.status_code >= 400:
        raise RuntimeError(f"Шлюз ответил {resp.status_code}: {_body_excerpt(resp.text)}")

    return resp.json()


async def update_credentials(login: str, password: str) -> dict:
    result = await _request("PUT", "/api/v1/auth/mis-credentials", json={"mis_login": login, "mis_password": password})
    # _request отдаёт тело 502-ответа без исключения, поэтому проверяем сами.
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(_gateway_error(result))
    return result


async def get_config() -> dict[str, Any]:
    result = await _request("GET", "/api/v1/auth/mis-config")
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


async def update_config(base_url: str) -> dict[str, Any]:
    result = await _request("PUT", "/api/v1/auth/mis-config", json={"base_url": base_url})
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(_gateway_error(result))
    invalidate_token()
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


async def get_credentials_status() -> dict[str, Any]:
    result = await _request("GET", "/api/v1/auth/mis-credentials")
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(_gateway_error(result))
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


async def search_patients(params: dict) -> dict:
    return await _request("POST", "/api/v1/mis/search-patients", json=params)


async def get_person_card(params: dict) -> dict:
    return await _request("POST", "/api/v1/mis/get-person-card", json=params)


async def get_regions_id(params: dict) -> dict:
    return await _request("POST", "/api/v1/mis/get-regions-id", json=params)


async def save_person_card(params: dict) -> dict:
    return await _request("POST", "/api/v1/mis/save-person-card", json=params)
