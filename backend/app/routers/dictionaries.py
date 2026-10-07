import logging
import os
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.services import dict_db, mis_client, region_links, settings_db, tfoms_parser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dictionaries", tags=["dictionaries"])

# Каталог с XML-выгрузками ТФОМС (SPSMO.zip, SPMO.zip, SPDEPT.xml).
TFOMS_DIR = os.getenv("TFOMS_DIR", "/app/tfoms")

# Способы загрузки по видам справочников. Других нет:
#   regions — только из ЕЦП, файл не подходит: участки принадлежат конкретному ЛПУ;
#   остальные — только XML-выгрузка ТФОМС.
SOURCES = {
    "regions": "ecp",
    "spmo": "tfoms",
    "spsmo": "tfoms",
    "spdept": "tfoms",
}


class LoadRequest(BaseModel):
    kind: str
    scope: str = ""


class RegionLinkRequest(BaseModel):
    """Привязка кода подразделения ИАС-4 к участку ЕЦП.

    Пустой regionId снимает привязку, но оставляет пометку «отвязано
    вручную»: автоподбор больше не будет предлагать этот код.
    """
    lpuId: str = ""
    podr: str
    regionId: str = ""
    regionName: str = ""


class RegionLinkBulkRequest(BaseModel):
    lpuId: str = ""
    links: list[dict] = []


def _unwrap(payload: Any) -> list[dict]:
    """Достаёт список из ответа ЕЦП/шлюза любой вложенности."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if payload.get("success") is False:
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(message or str(payload))
        for key in ("data", "rows", "items", "result"):
            if key in payload:
                return _unwrap(payload[key])
    return []


def _encoding() -> str:
    return (settings_db.get_settings().get("tfomsEncoding") or "cp1251").strip() or "cp1251"


def _find_tfoms_file(kind: str) -> str | None:
    """Ищет выгрузку в каталоге. Справочник подразделений ИАС-4 допускает и
    .xml, и .zip, поэтому перебираем оба расширения."""
    wanted = dict_db.TFOMS_FILES.get(kind)
    if not wanted or not os.path.isdir(TFOMS_DIR):
        return None
    base = os.path.splitext(wanted)[0].lower()
    for entry in sorted(os.listdir(TFOMS_DIR)):
        stem, ext = os.path.splitext(entry)
        if stem.lower() == base and ext.lower() in (".xml", ".zip"):
            return os.path.join(TFOMS_DIR, entry)
    return None


def _require_kind(kind: str) -> str:
    kind = (kind or "").strip()
    if kind not in dict_db.KINDS:
        raise HTTPException(status_code=400, detail=f"Неизвестный справочник: {kind}")
    return kind


@router.get("/status")
async def dictionaries_status():
    """Сколько записей в каждом справочнике и когда они загружались."""
    return {"items": dict_db.status()}


@router.get("/sources")
async def dictionary_sources():
    """Какие XML-выгрузки найдены на диске."""
    found, missing = [], []
    for kind, filename in dict_db.TFOMS_FILES.items():
        path = _find_tfoms_file(kind)
        item = {
            "kind": kind,
            "file": filename,
            "title": dict_db.KINDS.get(kind, kind),
            "path": path,
            "size": os.path.getsize(path) if path else None,
        }
        (found if path else missing).append(item)
    return {"directory": TFOMS_DIR, "found": found, "missing": missing}


@router.get("/log")
async def dictionaries_log(limit: int = Query(30, ge=1, le=200)):
    """История загрузок, включая неудачные."""
    return {"items": dict_db.load_log(limit)}


@router.post("/load")
async def load_dictionary(req: LoadRequest):
    """Обновляет справочник из его источника.

    Участки ЛПУ — только из ЕЦП. Справочники ТФОМС — только из XML-выгрузки,
    взятой из каталога TFOMS_DIR.
    """
    kind = _require_kind(req.kind)
    source = SOURCES[kind]
    settings = settings_db.get_settings()

    if source == "ecp":
        lpu_id = (req.scope or "").strip() or settings.get("misLpuId", "")
        if not lpu_id:
            raise HTTPException(status_code=400, detail="Для участков ЕЦП нужно указать Lpu_id")
        try:
            payload = await mis_client.get_regions_id({"Lpu_id": lpu_id, "isClose": "1"})
            count = dict_db.save_regions(lpu_id, _unwrap(payload))
        except Exception as e:
            logger.exception("Failed to load regions from ECP (lpu=%s)", lpu_id)
            dict_db.log_failure(kind, lpu_id, "ecp", str(e))
            raise HTTPException(status_code=502, detail=f"Не удалось получить участки из ЕЦП: {e}") from e
        return {"success": True, "kind": kind, "scope": lpu_id, "rows": count, "source": "ЕЦП"}

    path = _find_tfoms_file(kind)
    if not path:
        expected = dict_db.TFOMS_FILES[kind]
        dict_db.log_failure(kind, "", "tfoms", f"нет файла {expected}")
        raise HTTPException(
            status_code=404,
            detail=(
                f"Файл {expected} не найден в каталоге {TFOMS_DIR}. "
                "Положите выгрузку в этот каталог или загрузите её кнопкой «Загрузить XML»."
            ),
        )
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        detected, _, rows = tfoms_parser.parse_upload(os.path.basename(path), raw, _encoding())
        if detected != kind:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Файл {os.path.basename(path)} содержит справочник «{detected}», "
                    f"а обновляется «{kind}». Проверьте соответствие."
                ),
            )
        count = dict_db.save_entries(kind, "", rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to parse %s", path)
        dict_db.log_failure(kind, "", "tfoms", str(e))
        raise HTTPException(status_code=502, detail=f"Не удалось разобрать {os.path.basename(path)}: {e}") from e

    logger.info("Dictionary %s loaded from %s: %s rows", kind, os.path.basename(path), count)
    return {"success": True, "kind": kind, "scope": "", "rows": count,
            "source": os.path.basename(path)}


@router.post("/upload")
async def upload_dictionary(kind: str = Form(""), file: UploadFile = File(...)):
    """Загрузка XML-выгрузки ТФОМС файлом (zip с xml или сам xml).

    Участки ЛПУ не принимаются: они приходят только из ЕЦП, файлом их описать
    нельзя — они принадлежат конкретному ЛПУ.
    """
    filename = file.filename or "upload"
    lowered = filename.lower()
    if (kind or "").strip() == "regions":
        raise HTTPException(
            status_code=400,
            detail="Участки ЛПУ загружаются только из ЕЦП — нажмите «Обновить из ЕЦП».",
        )

    raw = await file.read()

    # Справочник подразделений ИАС-4 принимаем и в CSV: формат выгрузки
    # заказчика неизвестен, а колонки распознаются по заголовкам.
    if kind == "spdept" and lowered.endswith(".csv"):
        try:
            rows = tfoms_parser.parse_csv_spdept(raw.decode("utf-8-sig", errors="replace"))
        except Exception as e:
            logger.exception("Failed to parse uploaded %s", filename)
            raise HTTPException(status_code=400, detail=f"Не удалось разобрать CSV: {e}") from e
        if not rows:
            raise HTTPException(
                status_code=400,
                detail="В CSV нет ни одной записи с кодом подразделения "
                       "(ожидается колонка PODR или CODE).",
            )
        count = dict_db.save_entries("spdept", "", rows)
        logger.info("Dictionary spdept uploaded from %s: %s rows", filename, count)
        return {"success": True, "kind": "spdept", "scope": "", "rows": count, "source": filename}

    if not lowered.endswith((".zip", ".xml")):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ожидается XML-выгрузка ТФОМС (zip с xml или xml), получено: {filename}. "
                "Поддерживаются SPSMO.zip, SPMO.zip и SPDEPT.xml "
                "(для подразделений ИАС-4 подойдёт и CSV)."
            ),
        )
    try:
        detected, entry, rows = tfoms_parser.parse_upload(filename, raw, _encoding())
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to parse uploaded %s", filename)
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать файл: {e}") from e

    if kind and detected != kind:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Файл {filename} содержит справочник «{dict_db.KINDS.get(detected, detected)}», "
                f"а выбран «{dict_db.KINDS.get(kind, kind)}»."
            ),
        )

    count = dict_db.save_entries(detected, "", rows)
    logger.info("Dictionary %s uploaded from %s: %s rows", detected, filename, count)
    return {"success": True, "kind": detected, "scope": "", "rows": count,
            "source": filename, "entry": entry}


@router.get("/regions")
async def list_regions(lpuId: str = Query("", alias="lpuId")):
    lpu_id = lpuId or settings_db.get_settings().get("misLpuId", "")
    return {"items": dict_db.get_regions(lpu_id), "lpuId": lpu_id}


# Сколько записей отдавать за раз. Даже небольшой справочник лучше открывать
# постранично: полная выгрузка в таблицу браузера рано или поздно мешает.
PAGE_LIMIT = 200
PAGE_LIMIT_MAX = 2000


@router.get("/entries")
async def list_entries(
    kind: str = Query(...),
    scope: str = Query(""),
    search: str = Query(""),
    limit: int = Query(PAGE_LIMIT, ge=0, le=PAGE_LIMIT_MAX),
    offset: int = Query(0, ge=0),
):
    if kind not in dict_db.TFOMS_KINDS:
        raise HTTPException(status_code=400, detail=f"Справочник «{kind}» не является простым списком")
    total = dict_db.count_entries(kind, scope, search)
    items = dict_db.get_entries(kind, scope, search, limit, offset)
    return {
        "items": items,
        "kind": kind,
        "scope": scope,
        "total": total,
        "limit": limit,
        "offset": offset,
        # limit=0 просит обратно весь справочник — для больших это опасно,
        # поэтому ограничиваем и явно предупреждаем в ответе.
        "truncated": bool(total > len(items)),
    }


# ------------------------------------------- сопоставление подразделений и участков

def _link_lpu_id(lpuId: str) -> str:
    """Lpu_id для сопоставления: из запроса, иначе из настроек."""
    lpu_id = (lpuId or "").strip() or settings_db.get_settings().get("misLpuId", "")
    if not lpu_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не задан Lpu_id: укажите его в настройках (шестерёнка) "
                "или передайте в параметре lpuId."
            ),
        )
    return lpu_id


@router.get("/region-links")
async def region_links_matrix(lpuId: str = Query("", alias="lpuId")):
    """Таблица сопоставления: коды подразделений ИАС-4 и участки ЕЦП."""
    lpu_id = _link_lpu_id(lpuId)
    regions = dict_db.get_regions(lpu_id)
    ias = region_links.mo_entries((settings_db.get_settings().get("defaultMo") or ""))
    matrix = region_links.build_matrix(lpu_id, regions, ias)
    matrix["mo"] = (settings_db.get_settings().get("defaultMo") or "").strip().lstrip("0")
    matrix["regionsLoaded"] = bool(regions)
    matrix["iasLoaded"] = bool(ias)
    if not regions:
        matrix["hint"] = (
            "Участки ЕЦП не загружены. Обновите их на вкладке «Справочники» "
            "кнопкой «Обновить из ЕЦП» — без них сопоставлять нечего."
        )
    elif not ias:
        matrix["hint"] = (
            "Справочник подразделений ИАС-4 не загружен. Загрузите файл SPDEPT.xml "
            "на вкладке «Справочники» — из него берутся коды для поля podr."
        )
    return matrix


@router.post("/region-links")
async def save_region_link(req: RegionLinkRequest):
    """Привязывает или отвязывает код подразделения ИАС-4."""
    lpu_id = _link_lpu_id(req.lpuId)
    podr = (req.podr or "").strip()
    if not podr:
        raise HTTPException(status_code=400, detail="Не указан код подразделения")

    region_id = (req.regionId or "").strip()
    region_name = (req.regionName or "").strip()
    if region_id:
        regions = {r["region_id"]: r for r in dict_db.get_regions(lpu_id)}
        if region_id not in regions:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Участок {region_id} не найден среди участков ЛПУ {lpu_id}. "
                    "Обновите участки из ЕЦП и повторите."
                ),
            )
        region_name = regions[region_id]["name"] or region_name

    dict_db.save_region_link(lpu_id, podr, region_id, region_name, source="manual")
    logger.info(
        "Region link lpu=%s podr=%s → %s %s",
        lpu_id, podr, region_id or "(отвязано)", region_name,
    )
    return {
        "success": True,
        "lpuId": lpu_id,
        "podr": podr,
        "regionId": region_id,
        "regionName": region_name,
        "linked": bool(region_id),
    }


@router.post("/region-links/forget")
async def forget_region_link(req: RegionLinkRequest):
    """Убирает привязку полностью, чтобы код снова попал в автоподбор."""
    lpu_id = _link_lpu_id(req.lpuId)
    removed = dict_db.delete_region_link(lpu_id, (req.podr or "").strip())
    return {"success": True, "removed": bool(removed)}


@router.get("/region-links/suggest")
async def suggest_region_links(lpuId: str = Query("", alias="lpuId")):
    """Что предложил бы автоматический подбор. Ничего не сохраняет."""
    lpu_id = _link_lpu_id(lpuId)
    regions = dict_db.get_regions(lpu_id)
    ias = region_links.mo_entries((settings_db.get_settings().get("defaultMo") or ""))
    items = region_links.suggest(lpu_id, regions, ias)
    return {
        "lpuId": lpu_id,
        "items": items,
        "total": len(items),
        "note": (
            "Предложения не применены. Проверьте их и нажмите «Применить», "
            "при необходимости поправив вручную."
        ),
    }


@router.post("/region-links/apply")
async def apply_region_links(req: RegionLinkBulkRequest):
    """Применяет автоподбор. Ручные привязки и отвязки не трогаются."""
    lpu_id = _link_lpu_id(req.lpuId)
    items = [i for i in (req.links or []) if str(i.get("podr") or "").strip()]
    if not items:
        raise HTTPException(status_code=400, detail="Список привязок пуст")
    known = {r["region_id"] for r in dict_db.get_regions(lpu_id)}
    rejected = [i for i in items if str(i.get("region_id") or "") not in known]
    applied = [i for i in items if str(i.get("region_id") or "") in known]

    saved = dict_db.save_region_links(lpu_id, applied, source="auto") if applied else 0
    logger.info("Applied %s region links for lpu=%s", saved, lpu_id)
    return {
        "success": True,
        "lpuId": lpu_id,
        "applied": saved,
        "rejected": len(rejected),
        "rejectedCodes": [str(i.get("podr") or "") for i in rejected][:20],
    }
