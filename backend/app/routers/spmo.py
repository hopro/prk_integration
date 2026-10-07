import datetime
import logging

from fastapi import APIRouter

from app.services import dict_db, region_links, settings_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dict"])


@router.get("/dict")
async def dict_list():
    """СПМО и СМО из локального кэша XML-выгрузок ТФОМС."""
    result, sources = {}, {}
    for kind, key in (("spmo", "spmo"), ("spsmo", "spsmo")):
        rows = dict_db.get_entries(kind)
        result[key] = rows
        sources[key] = "cache" if rows else "not_loaded"

    loaded = all(s == "cache" for s in sources.values())
    payload = {
        **result,
        "source": "cache" if loaded else "not_loaded",
        "sources": sources,
    }
    if not loaded:
        payload["hint"] = (
            "Загрузите выгрузки ТФОМС SPSMO.zip и SPMO.zip на вкладке «Справочники»."
        )
    return payload


@router.get("/dict/spdept")
async def spdept_list(lpuId: str = "", mo: str = "", search: str = ""):
    """Подразделения ЛПУ для выбора кода, который уходит в ИАС-4 как podr.

    Источник — справочник подразделений ИАС-4 (файл SPDEPT). Список участков
    ЕЦП для этого не годится: там своя нумерация, и все коды с суффиксом _ГРП
    (40 из 107 участков) ИАС-4 отвергает ошибкой 501 «отсутствует в справочнике».
    Участки ЕЦП используются отдельно — при сопоставлении кода с участком при
    сохранении карты в ЕЦП.
    """
    # Коды берём у подразделений того МО, который указан в настройках, и только
    # те, что действуют на сегодня: в выгрузке ИАС-4 закрытые подразделения тоже
    # лежат (у МО 893 из 93 актуальны 79), а ИАС-4 их больше не принимает.
    today = datetime.date.today().isoformat()
    mo_code = mo.strip() or (settings_db.get_settings().get("defaultMo") or "").strip().lstrip("0")
    all_of_mo = dict_db.get_entries("spdept", mo_code)
    rows = [r for r in all_of_mo if r.get("valid_until") in ("", "9999-12-31") or r["valid_until"] >= today]
    if not rows and all_of_mo:
        # Ничего актуального не нашлось — показываем все, иначе форма будет пустой.
        rows = all_of_mo

    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r["code"].lower()
            or needle in r["name"].lower()
            or needle in r["extra"].lower()
        ]

    payload = {
        "spdept": [{"code": r["code"], "name": r["name"]} for r in rows],
        "source": "ias" if rows else "not_loaded",
        "mo": mo_code,
        "total": len(all_of_mo),
        "actual": len(rows),
        "expired": len(all_of_mo) - len(rows),
    }
    if not rows:
        payload["hint"] = (
            "Справочник подразделений ИАС-4 не загружен. Загрузите файл "
            "SPDEPT.xml (или .zip, .csv) на вкладке «Справочники» — без него коды "
            "подразделений взять неоткуда, а список участков ЕЦП содержит другую "
            "нумерацию, которую ИАС-4 не принимает."
        )
    return payload


@router.get("/dict/spdept/coverage")
async def spdept_coverage(lpuId: str = ""):
    """Сколько подразделений ИАС-4 привязано к участкам ЕЦП.

    Считается тем же кодом, что и страница «Сопоставление участков», чтобы
    два ответа об одном и том же не расходились.
    """
    lpu_id = lpuId or settings_db.get_settings().get("misLpuId", "")
    regions = dict_db.get_regions(lpu_id)
    ias = dict_db.get_entries("spdept")
    matrix = region_links.build_matrix(lpu_id, regions, ias)
    return {"lpuId": lpu_id, **matrix["summary"]}
