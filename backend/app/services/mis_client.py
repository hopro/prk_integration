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
BACKEND_SERVICE = "prk-backend"
BACKEND_HEALTH = "/api/health"
LOGIN_ROUTE = "/api/v1/auth/login"


def _peer(resp: httpx.Response) -> str:
    """Адрес, с которым соединён клиент httpx (если транспорт его отдаёт)."""
    try:
        stream = resp.extensions.get("network_stream")
        if stream is not None:
            addr = stream.get_extra_info("server_addr")
            if addr:
                return f"{addr[0]}:{addr[1]}"
    except Exception:  # noqa: BLE001 — диагностика не должна ломать запрос
        pass
    return "неизвестно"


def tcp_probe(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Куда реально уходит соединение.

    httpx не отдаёт адрес пира (у anyio-транспорта server_addr пуст), поэтому
    подключаемся сами и берём getpeername. Заодно видно, какие из адресов,
    на которые разрешилось имя, действительно отвечают — с именем в конфиге
    иначе не разберёшься.
    """
    parsed = urlparse(url)
    host = parsed.hostname or url
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    report: dict[str, Any] = {"host": host, "port": port, "addresses": []}

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as e:
        report["resolveError"] = f"{type(e).__name__}: {e}"
        return report

    seen = []
    for family, socktype, proto, _canon, sockaddr in infos:
        addr = f"{sockaddr[0]}:{sockaddr[1]}"
        if addr in seen:
            continue
        seen.append(addr)
        entry: dict[str, Any] = {"address": addr, "connected": False}
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            entry["connected"] = True
            peer = sock.getpeername()
            entry["peer"] = f"{peer[0]}:{peer[1]}"
        except OSError as e:
            entry["error"] = f"{type(e).__name__}: {e}"
        finally:
            if sock is not None:
                sock.close()
        report["addresses"].append(entry)

    connected = [a for a in report["addresses"] if a.get("connected")]
    report["connected"] = len(connected)
    report["total"] = len(report["addresses"])
    report["peer"] = connected[0].get("peer") if connected else None
    return report


async def probe_gateway() -> dict[str, Any]:
    """Отвечает ли по MIS_GATEWAY_URL именно наш шлюз.

    Проверяет по порядку: куда уходит соединение (tcp), что за сервис там
    (/health и /api/health — у шлюза и у backend метки разные) и есть ли
    маршрут входа. Ничего не меняет, только читает.
    """
    result: dict[str, Any] = {"url": MIS_GATEWAY_URL, "isGateway": False}

    tcp = tcp_probe(MIS_GATEWAY_URL)
    result["tcp"] = tcp
    result["peer"] = tcp.get("peer")
    if not tcp.get("connected"):
        result["reason"] = (
            f"По адресу {MIS_GATEWAY_URL} соединение не устанавливается. "
            f"Имя разрешилось в {', '.join(a['address'] for a in tcp['addresses']) or 'ничего'}, "
            f"отвечающих адресов: {tcp.get('connected', 0)} из {tcp.get('total', 0)}."
        )
        logger.error("МИС-ШЛЮЗ: %s", result["reason"])
        return result

    # Метку сервиса ищем на обоих адресах: /health есть у шлюза,
    # /api/health — у backend.
    service = None
    probes = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), verify=False) as client:
        for path in (GATEWAY_HEALTH, BACKEND_HEALTH):
            try:
                resp = await client.get(f"{MIS_GATEWAY_URL}{path}")
            except httpx.RequestError as e:
                probes[path] = {"error": f"{type(e).__name__}: {e}"}
                continue
            probes[path] = {"status": resp.status_code}
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                if isinstance(body, dict) and body.get("service"):
                    service = body["service"]
                    probes[path]["service"] = service
    result["probes"] = probes
    result["service"] = service
    result["healthStatus"] = probes.get(GATEWAY_HEALTH, {}).get("status")

    if service == BACKEND_SERVICE:
        result["isBackend"] = True
        result["reason"] = (
            f"MIS_GATEWAY_URL={MIS_GATEWAY_URL} указывает на САМ backend "
            f"(service={BACKEND_SERVICE}, соединение приземлилось на {tcp.get('peer')}), "
            "а не на шлюз ЕЦП. Уберите это значение из .env — тогда подставится "
            "адрес шлюза из compose (gateway:8010) — либо укажите адрес шлюза явно."
        )
        logger.error("МИС-ШЛЮЗ: %s", result["reason"])
        return result

    # Второй признак, не зависящий от версии шлюза: наш маршрут входа
    # отвечает 401 или 422, а чужое приложение — 404.
    login_status = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0), verify=False
        ) as client:
            resp = await client.post(f"{MIS_GATEWAY_URL}{LOGIN_ROUTE}", json={})
        login_status = resp.status_code
    except httpx.RequestError as e:
        result["loginError"] = f"{type(e).__name__}: {e}"
    result["loginStatus"] = login_status

    marked = service == GATEWAY_SERVICE
    has_route = login_status not in (None, 404, 405)
    result["isGateway"] = marked or has_route
    result["byMarker"] = marked

    if not result["isGateway"]:
        result["reason"] = (
            f"По адресу {MIS_GATEWAY_URL} (соединение приземлилось на "
            f"{tcp.get('peer')}) отвечает не наш шлюз: "
            f"на /health — {probes.get(GATEWAY_HEALTH, {}).get('status')}, "
            f"на {LOGIN_ROUTE} — {login_status}. Проверьте MIS_GATEWAY_URL: "
            "по этому адресу слушает другая программа."
        )

    logger.info(
        "МИС-ШЛЮЗ: url=%s пир=%s сервис=%s вход=%s наш_шлюз=%s",
        MIS_GATEWAY_URL, tcp.get("peer"), service, login_status, result["isGateway"],
    )
    if not result["isGateway"]:
        logger.error("МИС-ШЛЮЗ: %s", result["reason"])
    return result


async def _login_once() -> httpx.Response:
    """Одна попытка входа в шлюз. Сетевые ошибки пробрасываются вызывающему."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0), verify=False
    ) as client:
        resp = await client.post(
            f"{MIS_GATEWAY_URL}{LOGIN_ROUTE}",
            json={"login": GATEWAY_LOGIN, "password": GATEWAY_PASSWORD},
        )
    logger.info(
        "МИС-ШЛЮЗ вход: url=%s/%s peer=%s login=%s ответ=%s",
        MIS_GATEWAY_URL, LOGIN_ROUTE, _peer(resp), GATEWAY_LOGIN,
        _body_excerpt(resp.text, 200),
    )
    return resp


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
            f"По адресу {MIS_GATEWAY_URL} (пир {_peer(resp)}) нет шлюза ЕЦП: "
            f"{resp.status_code} на {LOGIN_ROUTE}, тело {_body_excerpt(resp.text, 200)}"
        ))
    if resp.status_code >= 400:
        detail = _body_excerpt(resp.text, 200)
        logger.error(
            "МИС-ШЛЮЗ: вход отклонён %s на %s (пир %s): %s",
            resp.status_code, MIS_GATEWAY_URL, _peer(resp), detail,
        )
        raise RuntimeError(
            f"Шлюз ЕЦП по адресу {MIS_GATEWAY_URL} (пир {_peer(resp)}) "
            f"отклонил вход: {resp.status_code} {detail}"
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
