import logging
import socket
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import settings_db, mis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class MisCredentialsPayload(BaseModel):
    login: str
    password: str


class MisConfigPayload(BaseModel):
    baseUrl: str


@router.put("/mis-credentials")
async def update_mis_credentials(payload: MisCredentialsPayload):
    login = (payload.login or "").strip()
    password = payload.password or ""

    # Валидируем ДО любой записи. Раньше пустой логин попадал в SQLite, а шлюз
    # отвечал 422 — базы расходились, и шестерёнка показывала нерабочий логин.
    missing = [
        name for name, value in (("Логин ЕЦП", login), ("Пароль ЕЦП", password)) if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Не заполнено: {', '.join(missing)}. Оба поля обязательны.",
        )

    # Сначала шлюз (он источник правды и ходит в ЕЦП), потом локальное зеркало.
    try:
        await mis_client.update_credentials(login, password)
    except Exception as e:
        logger.exception("Failed to push ECP credentials to gateway")
        raise HTTPException(
            status_code=502,
            detail=f"Шлюз не принял учётные данные ЕЦП: {e}",
        ) from e

    settings_db.save_settings({"misLogin": login, "misPassword": password})
    logger.info("ECP credentials saved and pushed to gateway: mis_login=%s", login)

    return {"success": True, "misLogin": login}


@router.get("/mis-credentials")
async def get_mis_credentials():
    """Состояние учётных данных ЕЦП по данным шлюза (источник правды)."""
    try:
        status = await mis_client.get_credentials_status()
    except Exception as e:
        logger.warning("Failed to read ECP credentials status from gateway: %s", e)
        return {"success": False, "error": f"Шлюз недоступен: {e}"}
    return {"success": True, "data": status}


@router.get("/mis-config")
async def get_mis_config():
    """Адрес ЕЦП, с которым реально работает шлюз."""
    try:
        return {"success": True, "data": await mis_client.get_config()}
    except Exception as e:
        logger.warning("Failed to read MIS config from gateway: %s", e)
        return {"success": False, "error": f"Шлюз недоступен: {e}"}


@router.put("/mis-config")
async def update_mis_config(payload: MisConfigPayload):
    """Меняет адрес ЕЦП на шлюзе. Проверяем обращением, а не записью в БД:
    иначе опечатка в адресе обнаружится только при первом обращении к ЕЦП."""
    base_url = (payload.baseUrl or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="Адрес ЕЦП не может быть пустым.")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail=f"Адрес ЕЦП должен начинаться с http:// или https:// (получено: {base_url}).",
        )

    try:
        result = await mis_client.update_config(base_url)
    except Exception as e:
        logger.exception("Failed to push MIS base URL to gateway")
        raise HTTPException(
            status_code=502, detail=f"Шлюз не принял адрес ЕЦП: {e}"
        ) from e

    settings_db.save_settings({"ecpUrl": result.get("baseUrl", base_url)})
    logger.info("ECP base URL saved and pushed to gateway: %s", result.get("baseUrl"))
    return {"success": True, "data": result}


@router.get("/gateway-health")
async def gateway_health():
    """Проверка связи backend → шлюз ЕЦП с разбором по шагам.

    Нужна, когда в логах «шлюз недоступен»: показывает, на каком шаге связь
    рвётся — имя не разрешается, порт не слушается или отвечает шлюз.
    Не обращается к ЕЦП и ничего не меняет.
    """
    url = mis_client.MIS_GATEWAY_URL
    parsed = urlparse(url)
    host = parsed.hostname or url
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    report: dict = {
        "gatewayUrl": url,
        "host": host,
        "port": port,
        "steps": {},
    }

    started = time.monotonic()
    try:
        addresses = sorted({ai[4][0] for ai in socket.getaddrinfo(host, port)})
        report["steps"]["resolve"] = {"ok": True, "addresses": addresses}
    except OSError as e:
        report["steps"]["resolve"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        report["ok"] = False
        report["hint"] = (
            "Имя шлюза не разрешается. Внутри сети compose адрес шлюза — "
            "http://gateway:8010. Проверьте, что сервис называется gateway и запущен."
        )
        return report

    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5.0):
            report["steps"]["tcp"] = {
                "ok": True,
                "ms": round((time.monotonic() - started) * 1000),
            }
    except OSError as e:
        report["steps"]["tcp"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "ms": round((time.monotonic() - started) * 1000),
        }
        report["ok"] = False
        report["hint"] = (
            f"Порт {port} на {host} не принимает соединения. Проверьте, что контейнер "
            "шлюза запущен (`docker compose ps gateway`) и слушает 0.0.0.0, а не "
            "127.0.0.1. Если имя разрешается во внешний адрес — отключите dns_search "
            "или укажите MIS_GATEWAY_URL с IP-адресом контейнера шлюза."
        )
        return report

    # Отвечает ли по этому адресу именно наш шлюз. Без этой проверки самая
    # частая ошибка выглядит загадочно: на /api/v1/auth/login приходит
    # 404 {"detail":"Not Found"} от посторонней программы.
    probe = await mis_client.probe_gateway()
    report["steps"]["probe"] = probe
    if not probe.get("isGateway"):
        report["ok"] = False
        report["hint"] = probe.get("reason") or "По этому адресу нет нашего шлюза."
        return report
    report["steps"]["gatewayIdentity"] = {
        "ok": True,
        "service": probe.get("service"),
        "byMarker": probe.get("byMarker"),
        "note": (
            "маркер сервиса подтверждён"
            if probe.get("byMarker")
            else "маркера нет (старая сборка шлюза), маршрут входа отвечает как у шлюза"
        ),
    }

    try:
        status = await mis_client.get_credentials_status()
        report["steps"]["login"] = {"ok": True, "credentials": status}
        report["ok"] = True
    except Exception as e:  # noqa: BLE001
        report["steps"]["login"] = {"ok": False, "error": str(e) or type(e).__name__}
        report["ok"] = False
        report["hint"] = "Шлюз отвечает, но вход не удался: " + (str(e) or type(e).__name__)

    return report
