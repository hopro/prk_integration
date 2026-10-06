import logging

import bcrypt
from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_refresh_token, decode_refresh_token
from app.common.dependencies import get_current_user
from app.common.exceptions import CredentialsError, MisAuthError, TokenInvalidError
from app.common.response import unified_ok, unified_error
from app.database import get_db
from app.mis.client import mis_client
from app.mis.schemas import UnifiedResponse
from app.mis.session import delete_mis_session, get_mis_session
from app.redis_client import get_redis
from app.users.models import User
from app.users.schemas import (
    LoginRequest,
    MisConfigUpdate,
    MisCredentialsStatus,
    MisCredentialsUpdate,
    RefreshRequest,
)

logger = logging.getLogger(__name__)

# Адрес ЕЦП, заданный через API. Хранится в Redis без TTL, чтобы пережить рестарт.
BASE_URL_KEY = "mis_config:base_url"

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post(
    "/login",
    summary="Авторизация пользователя",
    description=(
        "Аутентификация по локальному логину/паролю, после чего происходит "
        "автоматическая авторизация во внешней МИС.\n\n"
        "**Алгоритм:**\n"
        "1. Проверка локального пароля (bcrypt) против БД\n"
        "2. Авторизация в МИС по `mis_login`/`mis_password` из профиля (или логин/пароль из запроса)\n"
        "3. Сохранение сессии МИС в Redis\n"
        "4. Выдача JWT access_token + refresh_token\n\n"
        "**Refresh token:** одноразовый, действителен 7 дней. При обновлении старый отзывается.\n\n"
        "**Ответ:**\n"
        "- `access_token` — JWT для заголовка `Authorization: Bearer <token>` (30 мин)\n"
        "- `refresh_token` — для обновления пары токенов через `/refresh`\n"
        "- `token_type` — всегда `bearer`"
    ),
    responses={
        200: {
            "description": "Успешная авторизация",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "access_token": "eyJhbGciOiJIUzI1NiIs...",
                            "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
                            "token_type": "bearer",
                        },
                        "error": None,
                    }
                }
            },
        },
        401: {"description": "Неверный логин или пароль"},
        502: {"description": "Ошибка авторизации во внешней МИС"},
    },
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == body.login))
    user = result.scalar_one_or_none()

    if user is None or not bcrypt.checkpw(
        body.password.encode("utf-8"),
        user.password_hash.encode("utf-8"),
    ):
        return unified_error("INVALID_CREDENTIALS", "Invalid login or password", 401)

    mis_login = user.mis_login or user.login
    mis_pass = user.mis_password or body.password

    redis_con = await get_redis()
    try:
        mis_session = await mis_client.authenticate(mis_login, mis_pass)
        await delete_mis_session(redis_con, user.id)
        await mis_session.save(redis_con, user.id)
    except Exception as e:
        logger.warning("MIS auth failed during login for user %s: %s", user.login, e)

    access_token = create_access_token(user.id)
    refresh_token, jti = create_refresh_token(user.id)

    await redis_con.set(f"refresh_token:{user.id}:{jti}", user.id, ex=60 * 60 * 24 * 7)

    return unified_ok({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    })


@router.post(
    "/refresh",
    summary="Обновление JWT токенов",
    description=(
        "Обновляет пару access_token + refresh_token по действующему refresh_token.\n\n"
        "**Важно:** refresh_token одноразовый. Старый отзывается, выдаётся новый.\n"
        "Если refresh_token уже был использован — вернёт ошибку `TOKEN_INVALID`.\n\n"
        "Срок жизни нового refresh_token — 7 дней."
    ),
    responses={
        200: {
            "description": "Токены обновлены",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "access_token": "eyJhbGciOiJIUzI1NiIs...",
                            "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
                            "token_type": "bearer",
                        },
                        "error": None,
                    }
                }
            },
        },
        401: {"description": "Refresh token истёк, недействителен или отозван"},
    },
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_refresh_token(body.refresh_token)
    if payload is None:
        return unified_error("TOKEN_INVALID", "Invalid or expired refresh token", 401)

    user_id = payload.get("sub")
    jti = payload.get("jti")

    redis_con = await get_redis()
    key = f"refresh_token:{user_id}:{jti}"
    stored = await redis_con.get(key)
    if stored is None:
        return unified_error("TOKEN_INVALID", "Refresh token has been revoked", 401)

    await redis_con.delete(key)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return unified_error("USER_NOT_FOUND", "User not found or inactive", 401)

    new_access = create_access_token(user.id)
    new_refresh, new_jti = create_refresh_token(user.id)

    await redis_con.set(f"refresh_token:{user.id}:{new_jti}", user.id, ex=60 * 60 * 24 * 7)

    return unified_ok({
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    })


@router.post(
    "/logout",
    summary="Выход из системы",
    description=(
        "Завершает сессию: удаляет сессию МИС из Redis и отзывает все refresh_token пользователя.\n\n"
        "Требует `Authorization: Bearer <access_token>`."
    ),
    responses={
        200: {
            "description": "Выход выполнен",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {"message": "Logged out successfully"},
                        "error": None,
                    }
                }
            },
        },
        401: {"description": "Не авторизован"},
    },
)
async def logout(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis_con = await get_redis()

    await delete_mis_session(redis_con, user.id)

    pattern = f"refresh_token:{user.id}:*"
    async for key in redis_con.scan_iter(match=pattern):
        await redis_con.delete(key)

    return unified_ok({"message": "Logged out successfully"})


@router.get(
    "/mis-config",
    summary="Конфигурация подключения к ЕЦП",
    description=(
        "Возвращает базовый адрес ЕЦП, с которым работает шлюз.\n\n"
        "Источник правды — шлюз: внешнее приложение должно ориентироваться на "
        "это значение, а не на свой локальный адрес.\n\n"
        "Требует `Authorization: Bearer <access_token>`."
    ),
    response_model=UnifiedResponse,
)
async def get_mis_config(
    user: User = Depends(get_current_user),
):
    return unified_ok({"baseUrl": mis_client.base_url})


@router.put(
    "/mis-config",
    summary="Изменение адреса ЕЦП",
    description=(
        "Меняет базовый адрес ЕЦП. После смены сессия ЕЦП сбрасывается — "
        "новая создастся автоматически при следующем запросе.\n\n"
        "Требует `Authorization: Bearer <access_token>`."
    ),
    responses={
        200: {"description": "Адрес обновлён"},
        401: {"description": "Не авторизован"},
    },
)
async def update_mis_config(
    body: MisConfigUpdate,
    user: User = Depends(get_current_user),
):
    base_url = body.base_url.strip().rstrip("/")
    if not base_url:
        return unified_error("MIS_CONFIG_INVALID", "Адрес ЕЦП не может быть пустым", 400)
    if not base_url.startswith(("http://", "https://")):
        return unified_error(
            "MIS_CONFIG_INVALID",
            f"Адрес ЕЦП должен начинаться с http:// или https:// (получено: {base_url})",
            400,
        )

    previous = mis_client.base_url
    mis_client.set_base_url(base_url)
    logger.info("MIS base URL updated: %s -> %s", previous, base_url)

    # Сессия принадлежала прежнему ЕЦП — выбрасываем её у всех пользователей.
    # Адрес сохраняем в Redis, чтобы пережить перезапуск шлюза.
    redis_con = await get_redis()
    pattern = "mis_session:*"
    async for key in redis_con.scan_iter(match=pattern):
        await redis_con.delete(key)
    await redis_con.set(BASE_URL_KEY, mis_client.base_url)

    return unified_ok({"baseUrl": mis_client.base_url})


@router.get(
    "/mis-credentials",
    summary="Текущие учётные данные МИС",
    description=(
        "Возвращает логин ЕЦП, признак наличия пароля и время последнего изменения.\n\n"
        "Пароль не отдаётся. Нужен, чтобы внешнее приложение видело фактическое "
        "состояние учётных данных, а не только свою локальную копию.\n\n"
        "Требует `Authorization: Bearer <access_token>`."
    ),
    response_model=UnifiedResponse,
)
async def get_mis_credentials(
    user: User = Depends(get_current_user),
):
    return unified_ok(
        MisCredentialsStatus(
            mis_login=user.mis_login or user.login,
            password_set=bool(user.mis_password),
            updated_at=user.updated_at.isoformat() if user.updated_at else None,
        ).model_dump()
    )


@router.put(
    "/mis-credentials",
    summary="Обновление учётных данных МИС",
    description=(
        "Позволяет изменить логин/пароль для авторизации во внешней МИС.\n"
        "После обновления сессия МИС сбрасывается и создаётся заново с новыми "
        "данными — следующий запрос к МИС уже работает без ручного вмешательства.\n\n"
        "Требует `Authorization: Bearer <access_token>`."
    ),
    responses={
        200: {
            "description": "Учётные данные обновлены",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {"message": "MIS credentials updated"},
                        "error": None,
                    }
                }
            },
        },
        401: {"description": "Не авторизован"},
        502: {"description": "ЕЦП отклонила новые учётные данные"},
    },
)
async def update_mis_credentials(
    body: MisCredentialsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Сначала проверяем у ЕЦП и только потом коммитим: источник правды — шлюз,
    # поэтому в базе не должно оказаться логина/пароля, который ЕЦП отвергла.
    try:
        session = await mis_client.authenticate(body.mis_login, body.mis_password)
    except MisAuthError as e:
        logger.warning("MIS rejected new credentials for %s: %s", user.login, e)
        return unified_error("MIS_AUTH_FAILED", str(e), 502)
    except Exception as e:
        logger.exception("Failed to verify credentials against MIS")
        return unified_error(
            "MIS_REQUEST_FAILED", f"Не удалось проверить учётные данные: {e}", 502
        )

    user.mis_login = body.mis_login
    user.mis_password = body.mis_password
    await db.commit()

    logger.info("MIS credentials updated for %s: mis_login=%s", user.login, body.mis_login)

    # Пересоздаём сессию ЕЦП сразу, чтобы следующий запрос пациента работал
    # без ожидания ленивой переавторизации.
    redis_con = await get_redis()
    await mis_client.invalidate(redis_con, user.id, session)
    await session.save(redis_con, user.id)

    return unified_ok({"message": "MIS credentials updated"})
