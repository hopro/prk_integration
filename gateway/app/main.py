import logging
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI, Request
from sqlalchemy import select

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s: %(message)s",
    force=True,
)
# SQL-запросы и HTTP-обмен с ЕЦП заглушают собой полезные сообщения о сессиях.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

from app.common.exceptions import AppException
from app.common.response import unified_error
from app.config import get_settings
from app.database import Base, async_session_factory, engine
from app.redis_client import close_redis, get_redis, init_redis
from app.mis.client import mis_client
from app.users.models import User

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _seed_admin()
    await _restore_mis_base_url()

    yield

    await close_redis()
    await engine.dispose()


async def _restore_mis_base_url():
    """Возвращает адрес ЕЦП, заданный через API (иначе берётся из окружения)."""
    redis_con = await get_redis()
    stored = await redis_con.get("mis_config:base_url")
    if stored:
        mis_client.set_base_url(stored if isinstance(stored, str) else stored.decode())
        logger.info("MIS base URL restored from Redis: %s", mis_client.base_url)
    else:
        logger.info("MIS base URL from environment: %s", mis_client.base_url)


async def _seed_admin():
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.login == settings.admin_login))
        existing = result.scalar_one_or_none()
        if existing is None:
            pw_hash = bcrypt.hashpw(
                settings.admin_password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")
            user = User(
                login=settings.admin_login,
                password_hash=pw_hash,
                mis_login=settings.admin_mis_login or None,
                mis_password=settings.admin_mis_password or None,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            logger.info(
                "Seeded admin %s (mis_login=%s, mis_password configured=%s)",
                settings.admin_login,
                settings.admin_mis_login or None,
                bool(settings.admin_mis_password),
            )
        else:
            # Уже существующего пользователя НЕ перезаписываем: учётные данные ЕЦП
            # меняются только через PUT /api/v1/auth/mis-credentials.
            logger.info(
                "Admin %s exists: login=%s, mis_login=%s, mis_password configured=%s, updated_at=%s",
                existing.login,
                existing.login,
                existing.mis_login or None,
                bool(existing.mis_password),
                existing.updated_at,
            )


app = FastAPI(
    title="MIS Integration Gateway",
    description=(
        "API Gateway для интеграции с внешней Медицинской Информационной Системой (МИС).\n\n"
        "**Архитектура:**\n"
        "- Клиентское приложение → MIS Gateway (JWT auth) → Внешняя МИС\n"
        "- Сессия МИС хранится в Redis, пользователи — в PostgreSQL\n"
        "- Refresh токены с ротацией (одноразовые)\n\n"
        "**Как использовать (стороннее приложение):**\n"
        "1. `POST /api/v1/auth/login` — авторизация (локальный пароль) → JWT токены\n"
        "2. `PUT /api/v1/auth/mis-credentials` — указать логин/пароль от МИС (если отличаются от локальных)\n"
        "3. `POST /api/v1/mis/search-patients` — поиск пациентов в МИС\n"
        "4. `POST /api/v1/mis/get-patient-info` — детальная информация по пациенту\n"
        "5. `POST /api/v1/mis/save-person-card` — создание/редактирование карты\n\n"
        "**Формат ответа (единый для всех эндпоинтов):**\n"
        "```json\n"
        '{"success": true, "data": {...}, "error": null}\n'
        '{"success": false, "data": null, "error": {"code": "ERROR_CODE", "message": "Описание"}}\n'
        "```\n\n"
        "**Коды ошибок:**\n"
        "- `INVALID_CREDENTIALS` — неверный логин/пароль (401)\n"
        "- `TOKEN_INVALID` — токен истёк или отозван (401)\n"
        "- `SESSION_NOT_FOUND` — сессия МИС не найдена, требуется перелогин (401)\n"
        "- `MIS_AUTH_FAILED` — ошибка авторизации во внешней МИС (502)\n"
        "- `MIS_HTML_ERROR` — МИС вернула HTML вместо JSON (502)\n"
        "- `MIS_ERROR` — МИС вернула бизнес-ошибку (502)\n"
        "- `MIS_REQUEST_FAILED` — ошибка соединения с МИС (502)"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return unified_error(exc.code, exc.message, exc.http_status)


from app.auth.router import router as auth_router
from app.mis.router import router as mis_router

app.include_router(auth_router)
app.include_router(mis_router)


@app.get("/health", tags=["System"])
async def health():
    """Проверка живости.

    Поле service обязательно: по адресу шлюза иногда отвечает другая
    программа, и без метки отличить их нельзя — backend получал 404
    на /api/v1/auth/login и не понимал, что подключился не туда.
    """
    return {
        "status": "ok",
        "service": "mis-gateway",
        "ecpConfigured": bool(getattr(mis_client, "base_url", None)),
    }
