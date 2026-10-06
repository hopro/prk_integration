import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import settings_db, mis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsPayload(BaseModel):
    user: str = ""
    password: str = ""
    defaultMo: str = "0893"
    misLpuId: str = "13003795"
    misLogin: str = ""
    misPassword: str = ""
    iasUrl: str = ""
    iasCheckUrl: str = ""
    ecpUrl: str = ""
    tfomsEncoding: str = ""


@router.get("/settings")
async def get_settings_endpoint(includeMisStatus: bool = False):
    settings = settings_db.get_settings()
    if includeMisStatus:
        # Фактическое состояние учётных данных и адрес ЕЦП берём со шлюза —
        # он источник правды, локальная копия может разойтись с ним.
        try:
            settings["misStatus"] = await mis_client.get_credentials_status()
        except Exception as e:
            logger.warning("Gateway ECP credentials status unavailable: %s", e)
            settings["misStatus"] = None
        try:
            config = await mis_client.get_config()
            settings["ecpUrl"] = config.get("baseUrl") or settings["ecpUrl"]
        except Exception as e:
            logger.warning("Gateway MIS config unavailable: %s", e)
    return settings


@router.post("/settings")
async def save_settings_endpoint(payload: SettingsPayload):
    # Учётные данные ЕЦП и её адрес меняются только через
    # PUT /api/v1/auth/mis-credentials и /mis-config: там шлюз проверяет их перед
    # сохранением. Здесь сохраняем как есть, чтобы обычное сохранение настроек
    # (например, пароля ИАС-4) не затирало уже настроенные.
    #
    # Учитываем только реально присланные поля: у модели есть значения по
    # умолчанию, и без exclude_unset клиент, не присылающий адреса, затирал бы
    # их пустыми строками.
    values = payload.model_dump(exclude_unset=True)
    for key in ("user", "password", "defaultMo", "misLpuId"):
        if key not in values:
            values[key] = getattr(payload, key)
    return settings_db.save_settings(values)