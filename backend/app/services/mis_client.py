import asyncio
import os
import logging
import socket
from typing import Any
from urllib.parse import urlparse

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


# Метка, которую возвращает /health нашего шлюза. Если её нет — по адресу
# отвечает другая программа: у заказчика на настроенный адрес приходил
# 404 {"detail":"Not Found"}, и backend не мог понять, что подключился не туда.
GATEWAY_HEALTH = "/health"
GATEWAY_SERVICE = "mis-gateway"
LOGIN_ROUTE = "/api/v1/auth/login"


async def probe_gateway() -> dict[str, Any]:
    """Отвечает ли по MIS_GATEWAY_URL именно наш шлюз.

    Возвращает признак is_gateway и короткое объяснение. Ничего не меняет.
    """
    result: dict[str, Any] = {"url": MIS_GATEWAY_URL, "isGateway": False}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0), verify=False
        ) as client:
            resp = await client.get(f"{MIS_GATEWAY_URL}{GATEWAY_HEALTH}")
    except httpx.RequestError as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["reason"] = describe_unreachable(e)
        return result

    result["healthStatus"] = resp.status_code
    service = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            service = body.get("service")
    except Exception:
        pass
    if service:
        result["service"] = service

    # Второй признак, не зависящий от версии шлюза: наш маршрут входа
    # отвечает 401 или 422, а чужое приложение — 404.
    login_status = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0), verify=False
        ) as client:
            probe_login = await client.post(
                f"{MIS_GATEWAY_URL}{LOGIN_ROUTE}", json={}
            )
        login_status = probe_login.status_code
    except httpx.RequestError as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["reason"] = describe_unreachable(e)
        return result
    result["loginStatus"] = login_status

    marked = service == GATEWAY_SERVICE
    has_route = login_status not in (None, 404, 405)
    result["isGateway"] = marked or has_route
    result["byMarker"] = marked

    if not result["isGateway"]:
        result["reason"] = (
            f"По адресу {MIS_GATEWAY_URL} отвечает не наш шлюз: на /health — "
            f"{resp.status_code}, на {LOGIN_ROUTE} — {login_status}. "
            f"Проверьте MIS_GATEWAY_URL: по этому адресу слушает другая программа."
        )
    return result


async def _login_once() -> httpx.Response:
    """Одна попытка входа в шлюз. Сетевые ошибки пробрасываются вызывающему."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0), verify=False
    ) as client:
        return await client.post(
            f"{MIS_GATEWAY_URL}{LOGIN_ROUTE}",
            json={"login": GATEWAY_LOGIN, "password": GATEWAY_PASSWORD},
        )


def describe_unreachable(exc: Exception) -> str:
    """Человеческое объяснение, почему шлюз ЕЦП недоступен.

    httpx.connect-timeout приходит с пустым текстом, поэтому в сообщении
    пользователь видел только «Шлюз не принял адрес ЕЦП: ». Здесь собираем
    всё, что нужно для диагностики: адрес, куда шли, что именно сломалось
    и что проверить.
    """
    host = urlparse(MIS_GATEWAY_URL).hostname or MIS_GATEWAY_URL
    try:
        addresses = sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
    except OSError:
        addresses = []

    reason = str(exc).strip()
    kind = type(exc).__name__

    if isinstance(exc, httpx.ConnectTimeout):
        what = (
            f"{host} не отвечает на подключение по истечении таймаута "
            f"(проверено {LOGIN_ATTEMPTS} раз). Если DNS разрешает имя, но TCP-пакеты "
            "уходят в никуда — значит имя попало во внешний DNS через поисковый домен "
            "хоста."
            if addresses
            else f"{host} не отвечает на подключение (проверено {LOGIN_ATTEMPTS} раз)."
        )
        hint = (
            "Проверьте, что контейнер шлюза запущен и виден в той же сети compose "
            "(`docker compose ps`), а также что MIS_GATEWAY_URL указывает на имя "
            "сервиса gateway, а не на localhost. Если имя разрешается во внешний "
            "адрес — отключите dns_search или укажите MIS_GATEWAY_URL с IP-адресом "
            "контейнера шлюза. Частая причина — фильтрация на сетевом экране."
        )
    elif isinstance(exc, httpx.ConnectError) and addresses:
        what = f"соединение с {host} отклонено, хотя имя разрешается в {', '.join(addresses)}."
        hint = (
            "Контейнер шлюза не слушает порт 8010 или не запущен. Проверьте "
            "`docker compose logs gateway` и `docker compose ps gateway`."
        )
    elif isinstance(exc, httpx.ConnectError):
        what = f"не удалось подключиться к {host}."
        hint = (
            "Имя шлюза не разрешается. Внутри сети compose адрес шлюза — "
            "`http://gateway:8010`. Проверьте, что сервис называется gateway."
        )
    else:
        what = reason or f"не удалось подключиться к {host} ({kind})."
        hint = "Проверьте доступность шлюза ЕЦП."

    where = f" ({', '.join(addresses)})" if addresses else ""
    return f"Шлюз ЕЦП недоступен по адресу {MIS_GATEWAY_URL}{where}: {what} {hint}"


# Шлюз поднимается вместе с backend, но Postgres и Redis внутри него стартуют
# дольше. Пока шлюз не готов, вход повторяем — иначе первое же обращение к ЕЦП
# падает с ConnectTimeout, хотя через минуту всё работает.
LOGIN_ATTEMPTS = 6
LOGIN_BACKOFF_SEC = 2.0


async def _login() -> str:
    global _token
    last: Exception | None = None
    for attempt in range(1, LOGIN_ATTEMPTS + 1):
        try:
            resp = await _login_once()
        except httpx.RequestError as e:
            last = e
            if attempt < LOGIN_ATTEMPTS:
                logger.warning(
                    "MIS gateway unreachable (attempt %s/%s): %s",
                    attempt, LOGIN_ATTEMPTS, type(e).__name__,
                )
                await asyncio.sleep(LOGIN_BACKOFF_SEC)
                continue
            message = describe_unreachable(e)
            logger.error("MIS gateway login failed after %s attempts: %s", LOGIN_ATTEMPTS, message)
            raise RuntimeError(message) from e
        break
    else:  # pragma: no cover — защита на случай, пока цикл не отработал
        raise RuntimeError(describe_unreachable(last) if last else "Шлюз ЕЦП недоступен")

    if resp.status_code in (404, 405):
        probe = await probe_gateway()
        raise RuntimeError(probe.get("reason") or (
            f"По адресу {MIS_GATEWAY_URL} нет шлюза ЕЦП "
            f"({resp.status_code} на /api/v1/auth/login)."
        ))
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Шлюз ЕЦП отклонил вход ({resp.status_code}): {_body_excerpt(resp.text)}"
        )
    data = resp.json()
    _token = data.get("access_token") or data.get("data", {}).get("access_token")
    if not _token:
        raise RuntimeError(f"Шлюз ЕЦП не вернул токен: {_body_excerpt(str(data))}")
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

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=5.0), verify=False
        ) as client:
            resp = await client.request(
                method, f"{MIS_GATEWAY_URL}{path}", headers=headers, **kwargs
            )
    except httpx.RequestError as e:
        raise RuntimeError(describe_unreachable(e)) from e

    if resp.status_code == 401:
        token = await _login()
        headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=5.0), verify=False
            ) as client:
                resp = await client.request(
                    method, f"{MIS_GATEWAY_URL}{path}", headers=headers, **kwargs
                )
        except httpx.RequestError as e:
            raise RuntimeError(describe_unreachable(e)) from e

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
