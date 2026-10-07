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
async def spdept_list(mo: str = "", search: str = ""):
    """Подразделения ЛПУ для выбора кода, который уходит в ИАС-4 как podr.

    Источник — два справочника подразделений ИАС-4: SPDEPT (обычные
    подразделения) и SPSUBDEPT (ФАПы, медкабинеты, дневные стационары). Берутся
    подразделения той медицинской организации, которая указана в настройках, и
    только те, что действуют и разрешают прикрепление.

    Список участков ЕЦП для этого не годится: там своя нумерация, и все коды с
    суффиксом _ГРП (а это 40 из 107 участков) ИАС-4 отвергает с ошибкой 501.
    Участки ЕЦП нужны отдельно — по ним находится LpuRegion_id при сохранении
    карты в ЕЦП.
    """
    rows, summary = region_links.picker_entries(mo)

    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in r["code"].lower() or needle in r["name"].lower()
            or needle in r["extra"].lower()
        ]

    payload = {
        "spdept": [
            {"code": r["code"], "name": r["name"], "source": r["source"]} for r in rows
        ],
        "source": "ias" if summary["actual"] else "not_loaded",
        "mo": summary["mo"],
        "total": summary["total"],
        "actual": summary["actual"],
        "expired": max(0, summary["total"] - summary["actual"]),
    }
    if not summary["actual"]:
        payload["hint"] = (
            "Нет действующих подразделений для прикрепления. Проверьте, что "
            "загружены оба справочника ИАС-4 — SPDEPT.xml и SPSUBDEPT.xml, — "
            "и что код МО в настройках верный. Подразделения, у которых в "
            "выгрузке закрыт срок действия или снят признак «разрешено "
            "прикрепление», ИАС-4 не примет: на них он отвечает 501 и 502."
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
