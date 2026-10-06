import logging
import re
from typing import Any

from datetime import date

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import MisAuthError, MisHtmlError
from app.common.response import unified_ok, unified_error
from app.database import get_db
from app.mis.client import mis_client
from app.mis.schemas import UnifiedErrorResponse, UnifiedResponse
from app.mis.session import MisSession, get_mis_session
from app.redis_client import get_redis
from app.users.models import User

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


router = APIRouter(prefix="/api/v1/mis", tags=["MIS Proxy"])


async def _ensure_mis_session(user: User, redis_con) -> MisSession | None:
    mis_login = user.mis_login or user.login
    mis_pass = user.mis_password
    if not mis_pass:
        return None
    logger.info("MIS session: authenticating %s", mis_login)
    return await mis_client.ensure_session(mis_login, mis_pass, redis_con, user.id)


async def _fresh_mis_session(user: User, redis_con, reason: str):
    """Выбросить мёртвую сессию и получить новую. Возвращает (session, error).

    Сессия всегда удаляется из Redis ДО попытки переавторизации: иначе битая
    сессия остаётся в кэше и каждый следующий запрос падает с той же ошибкой,
    пока учётные данные вручную не пересохранят через шестерёнку.
    """
    await mis_client.invalidate(redis_con, user.id)
    try:
        session = await _ensure_mis_session(user, redis_con)
    except MisAuthError as e:
        return None, unified_error("MIS_AUTH_FAILED", str(e), 502)
    except Exception as e:
        logger.exception("MIS re-authentication failed")
        return None, unified_error(
            "MIS_REQUEST_FAILED", f"Не удалось переавторизоваться в ЕЦП: {_strip_html(str(e))}", 502
        )
    if session is None:
        return None, unified_error(
            "MIS_CREDENTIALS_NOT_SET",
            "Учётные данные ЕЦП не настроены. Задайте их через PUT /api/v1/auth/mis-credentials.",
            401,
        )
    logger.info("MIS session: re-authenticated after %s", reason)
    return session, None


async def _proxy_request(
    user: User,
    path: str,
    form_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
):
    redis_con = await get_redis()
    session = await get_mis_session(redis_con, user.id)

    if session is None:
        session, error = await _fresh_mis_session(user, redis_con, "отсутствующей сессии")
        if error is not None:
            return error

    for attempt in range(2):
        try:
            result = await mis_client.request(
                method="POST",
                path=path,
                session=session,
                data=form_data,
                params=params,
            )
            break
        except MisHtmlError as e:
            # HTML от ЕЦП = сессия недействительна (редирект на страницу входа).
            # Раньше переавторизация запускалась только если в тексте встречались
            # "logout"/"action", из-за чего мёртвая сессия навсегда оставалась в Redis.
            if attempt == 0:
                logger.warning("MIS session dead (%s), re-authenticating", e)
                session, error = await _fresh_mis_session(user, redis_con, f"{e}")
                if error is not None:
                    return error
                continue
            logger.error("MIS returned HTML again after re-authentication: %s", e)
            return unified_error(
                "MIS_SESSION_EXPIRED",
                f"Сессия ЕЦП не восстанавливается: {e}",
                502,
            )
        except MisAuthError as e:
            # Пароль не принят — сессию тоже выбрасываем, чтобы не кэшировать мусор.
            await mis_client.invalidate(redis_con, user.id)
            return unified_error("MIS_AUTH_FAILED", str(e), 502)
        except Exception as e:
            return unified_error("MIS_REQUEST_FAILED", _strip_html(str(e)), 502)

    if isinstance(result, dict):
        logger.info("MIS result keys=%s success=%r", result.keys(), result.get("success"))
        success = result.get("success")
        if success is False:
            err_msg = result.get("Error_Msg") or result.get("error") or result.get("message") or str(result)
            return unified_error("MIS_ERROR", _strip_html(err_msg), 502)
        err_msg = result.get("Error_Msg") or ""
        if err_msg.strip():
            return unified_error("MIS_ERROR", _strip_html(err_msg), 502)

    return unified_ok(result)


SEARCH_EXAMPLE = {
    "PersonSurName_SurName": "ТЕСТ",
    "PersonFirName_FirName": "",
    "PersonSecName_SecName": "",
    "PersonBirthDay_BirthDay": "",
    "Person_id": "",
    "Person_Snils": "",
    "Person_Inn": "",
    "Polis_Ser": "",
    "Polis_Num": "",
    "Polis_EdNum": "",
    "showAll": 1,
    "searchMode": "all",
    "allowOverLimit": 1,
    "Double_ids": "[]",
    "page": 1,
    "start": 0,
    "limit": 100,
}

PATIENT_INFO_EXAMPLE = {
    "Person_id": "660910003025820",
    "Server_id": "13003795",
    "type": 1,
    "userMedStaffFact_id": "",
    "userLpuUnitType_SysNick": "polka",
}

# Набор полей формы, который ЕЦП ожидает для списка участков.
REGION_FORM_FIELDS = (
    "LpuRegion_id", "syncStatus", "LpuRegion_Name", "LpuRegion_begDate",
    "LpuRegion_endDate", "LpuRegion_Descr", "LpuRegionType_Name",
    "LpuRegionTipUch", "LpuRegion_Status", "MedPersonal_FIO",
    "object", "isClose", "Lpu_id",
)

REGIONS_EXAMPLE = {
    "LpuRegion_id": "",
    "syncStatus": "",
    "LpuRegion_Name": "",
    "LpuRegion_begDate": "",
    "LpuRegion_endDate": "",
    "LpuRegion_Descr": "",
    "LpuRegionType_Name": "",
    "LpuRegionTipUch": "",
    "LpuRegion_Status": "",
    "MedPersonal_FIO": "",
    "object": "LpuRegion",
    "isClose": "1",
    "Lpu_id": "13003795",
}

SAVE_CARD_EXAMPLE = {
    "Person_id": "660910003025820",
    "PersonCard_id": "660101003012577",
    "PersonCard_Code": "12986",
    "PersonCard_begDate": "03.07.2026",
    "LpuRegion_id": "3389",
    "Server_id": "13003795",
    "action": "add",
    "LpuRegionType_id": "1",
    "Lpu_id": "13003795",
    "LpuAttachType_id": "1",
    "isPersonCardAttach": "1",
}


@router.post(
    "/search-patients",
    summary="Поиск пациентов в МИС",
    description=(
        "Прокси-запрос к МИС для поиска пациентов по различным критериям. "
        "Передаёт форму данных в МИС и возвращает список найденных пациентов.\n\n"
        "**Как использовать стороннему приложению:**\n"
        "1. Авторизоваться: `POST /api/v1/auth/login` → получить access_token\n"
        "2. Вызвать этот эндпоинт с `Authorization: Bearer <token>`\n"
        "3. Тело запроса — любые поля поиска, которые принимает МИС\n\n"
        "**Основные поля поиска:**\n"
        "- `PersonSurName_SurName` — фамилия (регистронезависимо, частичное совпадение)\n"
        "- `PersonFirName_FirName` — имя\n"
        "- `PersonSecName_SecName` — отчество\n"
        "- `PersonBirthDay_BirthDay` — дата рождения (ДД.ММ.ГГГГ)\n"
        "- `Person_Snils` — СНИЛС\n"
        "- `Person_Inn` — ИНН\n"
        "- `Polis_Ser` / `Polis_Num` / `Polis_EdNum` — полис\n"
        "- `page`, `start`, `limit` — пагинация\n\n"
        "**Ответ:** унифицированная обёртка, `data` содержит массив `data` с записями пациентов."
    ),
    response_model=UnifiedResponse,
    responses={
        200: {
            "description": "Успешный ответ от МИС",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "data": [
                                {
                                    "Person_id": "660910003025820",
                                    "Server_id": "13003795",
                                    "PersonEvn_id": "660101016522040",
                                    "PersonSurName_SurName": "ТЕСТОВ",
                                    "PersonFirName_FirName": "ГП4",
                                    "PersonSecName_SecName": "ТАГИЛ",
                                    "PersonBirthDay_BirthDay": "05.05.2001",
                                    "Person_Snils": "89956944020",
                                    "Person_Inn": "569875156789",
                                    "Person_Phone": "9991234567",
                                    "Person_IsDead": "false",
                                    "UAddress_AddressText": "622931, РОССИЯ, СВЕРДЛОВСКАЯ ОБЛ, Г НИЖНИЙ ТАГИЛ, ул. Примерная, д. 1,",
                                    "PAddress_AddressText": "622931, РОССИЯ, СВЕРДЛОВСКАЯ ОБЛ, Г НИЖНИЙ ТАГИЛ, ул. Примерная, д. 1,",
                                }
                            ]
                        },
                        "error": None,
                    }
                }
            },
        },
        401: {"model": UnifiedErrorResponse, "description": "Не авторизован или сессия МИС не найдена"},
        502: {"model": UnifiedErrorResponse, "description": "Ошибка при обращении к МИС (HTML или таймаут)"},
    },
)
async def search_patients(
    data: dict[str, Any] = Body(
        ...,
        examples=[SEARCH_EXAMPLE],
        description="Поля поиска. Передаются в МИС как form-data. Можно указать любые поля, которые принимает МИС.",
    ),
    user: User = Depends(get_current_user),
):
    path = "/"
    params = {"c": "Person", "m": "getPersonSearchGrid", "_dc": "0"}
    return await _proxy_request(user, path, form_data=data, params=params)


@router.post(
    "/get-patient-info",
    summary="Получить информацию о пациенте",
    description=(
        "Прокси-запрос к МИС для получения расширенной информации о пациенте "
        "по его Person_id и Server_id.\n\n"
        "**Как использовать стороннему приложению:**\n"
        "1. Авторизоваться\n"
        "2. Вызвать с `Person_id` и `Server_id` (получены из search-patients)\n\n"
        "**Ответ:** `data.personInfo` — массив с детальными данными пациента."
    ),
    response_model=UnifiedResponse,
    responses={
        200: {
            "description": "Информация о пациенте",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "Error_Msg": "",
                            "personInfo": [
                                {
                                    "Person_id": "660910003025820",
                                    "PersonEvn_id": "660101016522040",
                                    "Server_id": "13003795",
                                    "Person_Birthday": "05.05.2001",
                                    "Person_Age": "25",
                                    "Sex_Name": "Мужской",
                                    "Lpu_Nick": "ГАУЗ СО \"ГП г. Нижний Тагил\"",
                                    "Person_Snils": "89956944020",
                                    "Person_Inn": "569875156789",
                                    "Person_Phone": "9991234567 (БД)",
                                    "Person_PAddress": "Г НИЖНИЙ ТАГИЛ, ул. Примерная, д. 11,",
                                    "PersonCard_id": "7987744",
                                    "PersonCard_Code": "12986",
                                    "PersonCard_begDate": "31.10.2024",
                                }
                            ],
                        },
                        "error": None,
                    }
                }
            },
        },
        401: {"model": UnifiedErrorResponse, "description": "Не авторизован или сессия МИС не найдена"},
        502: {"model": UnifiedErrorResponse, "description": "Ошибка при обращении к МИС"},
    },
)
async def get_patient_info(
    data: dict[str, Any] = Body(
        ...,
        examples=[PATIENT_INFO_EXAMPLE],
        description=(
            "Параметры запроса. "
            "**Обязательные поля:** `Person_id`, `Server_id`. "
            "Остальные поля опциональны."
        ),
    ),
    user: User = Depends(get_current_user),
):
    path = "/"
    params = {"c": "EMK", "m": "getPersonInfo"}
    return await _proxy_request(user, path, form_data=data, params=params)


@router.post(
    "/save-person-card",
    summary="Сохранить карту пациента (прикрепление)",
    description=(
        "Прокси-запрос к МИС для создания/редактирования карты пациента (прикрепления к ЛПУ).\n\n"
        "**Как использовать стороннему приложению:**\n"
        "1. Авторизоваться\n"
        "2. Получить Person_id через search-patients\n"
        "3. Вызвать save-person-card с необходимыми полями\n\n"
        "**Поля запроса:** `Person_id`, `Server_id`, `PersonCard_id`, "
        "`PersonCard_Code`, `PersonCard_begDate`, `LpuRegion_id`, "
        "`action`, `LpuRegionType_id`, `Lpu_id`, `LpuAttachType_id`, "
        "`isPersonCardAttach`.\n\n"
        "**Примечание:** если `PersonCard_begDate` не передан, "
        "автоматически подставляется текущая дата (`ДД.ММ.ГГГГ`).\n\n"
        "**Ответ:** `data.success` — флаг успеха, `data.Error_Msg` — сообщение об ошибке (пусто при успехе)."
    ),
    response_model=UnifiedResponse,
    responses={
        200: {
            "description": "Результат сохранения карты",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": {
                            "PersonCard_id": "660101000482453",
                            "success": True,
                            "Error_Code": None,
                            "Error_Msg": "",
                            "PersonCardAttach_id": "660101000236849",
                            "Cancel_Error_Handle": True,
                        },
                        "error": None,
                    }
                }
            },
        },
        401: {"model": UnifiedErrorResponse, "description": "Не авторизован или сессия МИС не найдена"},
        502: {"model": UnifiedErrorResponse, "description": "Ошибка при обращении к МИС"},
    },
)
async def save_person_card(
    data: dict[str, Any] = Body(
        ...,
        examples=[SAVE_CARD_EXAMPLE],
        description=(
            "Параметры карты. "
            "Передаются в МИС как form-data. "
            "Все поля, поддерживаемые МИС."
        ),
    ),
    user: User = Depends(get_current_user),
):
    if not data.get("PersonCard_begDate"):
        data["PersonCard_begDate"] = date.today().strftime("%d.%m.%Y")
    path = "/"
    params = {"c": "PersonCard", "m": "savePersonCard"}
    return await _proxy_request(user, path, form_data=data, params=params)


PERSON_CARD_EXAMPLE = {
    "Person_id": "660910003025820",
    "Server_id": "13003795",
    "mode": "PersonInformationPanel",
    "additionalFields": "[]",
}

GET_PERSON_CARD_RESPONSE_EXAMPLE = [
    {
        "Person_id": "660910003025820",
        "PersonEvn_id": "660101016522040",
        "Server_id": "13003795",
        "Person_Birthday": "05.05.2001",
        "Person_Age": "25",
        "Person_Phone": "9991234567 (БД)",
        "Person_PAddress": "Г НИЖНИЙ ТАГИЛ, ул. Примерная, д. 11,",
        "Lpu_Nick": "ГАУЗ СО \"ГП г. Нижний Тагил\"",
        "PersonCard_id": "660101003012662",
        "PersonCard_Code": "12986",
        "PersonCard_begDate": "03.07.2026",
        "PersonCard_endDate": "",
        "LpuRegion_Name": "16",
    },
]


@router.post(
    "/get-person-card",
    summary="Получить карту пациента",
    description=(
        "Прокси-запрос к МИС для получения данных карты пациента.\n\n"
        "**Как использовать стороннему приложению:**\n"
        "1. Авторизоваться\n"
        "2. Вызвать с `Person_id` и `Server_id` (получены из search-patients)\n\n"
        "**Параметры:**\n"
        "- `Person_id` — ID пациента (обязательно)\n"
        "- `Server_id` — ID ЛПУ (обязательно)\n"
        "- `mode` — режим загрузки (по умолчанию `PersonInformationPanel`)\n"
        "- `additionalFields` — доп. поля (JSON-массив, по умолчанию `[]`)\n\n"
        "**Ответ:** массив с данными карты пациента в `data`."
    ),
    response_model=UnifiedResponse,
    responses={
        200: {
            "description": "Данные карты пациента",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": GET_PERSON_CARD_RESPONSE_EXAMPLE,
                        "error": None,
                    }
                }
            },
        },
        401: {"model": UnifiedErrorResponse, "description": "Не авторизован или сессия МИС не найдена"},
        502: {"model": UnifiedErrorResponse, "description": "Ошибка при обращении к МИС"},
    },
)
async def get_person_card(
    data: dict[str, Any] = Body(
        ...,
        examples=[PERSON_CARD_EXAMPLE],
        description=(
            "Параметры запроса. "
            "**Обязательные поля:** `Person_id`, `Server_id`."
        ),
    ),
    user: User = Depends(get_current_user),
):
    path = "/"
    params = {"c": "Common", "m": "loadPersonData"}
    return await _proxy_request(user, path, form_data=data, params=params)


GET_REGIONS_RESPONSE_EXAMPLE = [
    {
        "LpuRegion_id": "3215",
        "LpuRegion_Name": "16",
        "LpuRegion_Descr": "Вызов на дом",
        "LpuRegionType_id": "1",
        "LpuRegion_begDate": "01.11.2022",
        "LpuRegion_endDate": None,
        "MedPersonal_FIO": "ЧЕСКИДОВ ИВАН МИХАЙЛОВИЧ",
        "syncStatus": "2",
        "Lpu_id": "13003795",
    },
]


@router.post(
    "/get-regions-id",
    summary="Получить список участков ЛПУ",
    description=(
        "Прокси-запрос к МИС для получения списка участков ЛПУ по идентификатору.\n\n"
        "**Как использовать стороннему приложению:**\n"
        "1. Авторизоваться\n"
        "2. Вызвать с `Lpu_id` (Server_id из search-patients/get-patient-info)\n"
        "3. Полученный `LpuRegion_id` используется в `save-person-card`\n\n"
        "**Параметры:**\n"
        "- `Lpu_id` — ID ЛПУ (обязательно)\n"
        "- `object` — тип объекта (по умолчанию `LpuRegion`)\n"
        "- `isClose` — фильтр по статусу (1 — действующие)\n"
        "- Остальные поля (`LpuRegion_Name`, `MedPersonal_FIO`, ...) — фильтры поиска\n\n"
        "**Ответ:** массив участков в `data`."
    ),
    response_model=UnifiedResponse,
    responses={
        200: {
            "description": "Список участков",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": GET_REGIONS_RESPONSE_EXAMPLE,
                        "error": None,
                    }
                }
            },
        },
        401: {"model": UnifiedErrorResponse, "description": "Не авторизован или сессия МИС не найдена"},
        502: {"model": UnifiedErrorResponse, "description": "Ошибка при обращении к МИС"},
    },
)
async def get_regions_id(
    data: dict[str, Any] = Body(
        ...,
        examples=[REGIONS_EXAMPLE],
        description=(
            "Параметры запроса. "
            "**Обязательное поле:** `Lpu_id`. "
            "Остальные поля имеют значения по умолчанию."
        ),
    ),
    user: User = Depends(get_current_user),
):
    path = "/"
    params = {"c": "LpuStructure", "m": "getLpuRegion"}
    # ЕЦП ожидает весь набор полей формы — ровно то, что отправляет его веб-клиент.
    # Дописываем недостающие пустыми значениями, чтобы результат не зависел от того,
    # какие поля прислал вызывающий.
    form_data = {field: "" for field in REGION_FORM_FIELDS}
    form_data.update(data)
    return await _proxy_request(user, path, form_data=form_data, params=params)
