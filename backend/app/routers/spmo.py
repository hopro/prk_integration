import logging

from fastapi import APIRouter

from app.services import dict_db, region_match, settings_db

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
    rows = dict_db.get_entries("spdept", mo)
    if not rows:
        rows = dict_db.get_entries("spdept", "")

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
        "mo": mo,
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
    """Сколько подразделений ИАС-4 найдётся среди участков ЕЦП.

    Показывает, насколько выбранный справочник подразделений совпадает с
    участками ЕЦП: подразделение без участка нельзя прикрепить к ЛПУ в ЕЦП.
    """
    lpu_id = lpuId or settings_db.get_settings().get("misLpuId", "")
    regions = dict_db.get_regions(lpu_id)
    ia_regions = {region_match.region_code(r["name"]): r for r in regions}
    ia_regions = {c: r for c, r in ia_regions.items() if c}

    matched, missing = [], []
    for entry in dict_db.get_entries("spdept"):
        code = entry["code"]
        if code in ia_regions:
            matched.append({"code": code, "name": entry["name"], "region": ia_regions[code]["name"]})
        else:
            missing.append({"code": code, "name": entry["name"]})

    return {
        "lpuId": lpu_id,
        "regions": len(regions),
        "ias": len(dict_db.get_entries("spdept")),
        "matched": len(matched),
        "missing": missing[:200],
        "matchedSample": matched[:20],
    }