import logging

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