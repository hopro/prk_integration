import logging
import os
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.services import dict_db, mis_client, settings_db, tfoms_parser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dictionaries", tags=["dictionaries"])

# Каталог с XML-выгрузками ТФОМС (SPSMO.zip, SPMO.zip, SPFMODIVISION.zip).
TFOMS_DIR = os.getenv("TFOMS_DIR", "/app/tfoms")

# Способы загрузки по видам справочников. Других нет:
#   regions — только из ЕЦП, файл не подходит: участки принадлежат конкретному ЛПУ;
#   остальные — только XML-выгрузка ТФОМС.
SOURCES = {
    "regions": "ecp",
    "spmo": "tfoms",
    "spsmo": "tfoms",
    "spdiv": "tfoms",
    "spdept": "file",
}


class LoadRequest(BaseModel):
    kind: str
    scope: str = ""


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

    if source == "file":
        raise HTTPException(
            status_code=400,
            detail=(
                "Справочник подразделений ИАС-4 загружается файлом: положите выгрузку "
                "в каталог или нажмите «Загрузить файл». Это единственный источник кодов, "
                "которые ИАС-4 принимает в поле podr."
            ),
        )

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
                "Поддерживаются SPSMO.zip, SPMO.zip, SPFMODIVISION.zip, "
                "а для подразделений ИАС-4 ещё и CSV."
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


@router.get("/entries")
async def list_entries(
    kind: str = Query(...),
    scope: str = Query(""),
    search: str = Query(""),
    limit: int = Query(0, ge=0, le=5000),
):
    if kind not in dict_db.TFOMS_KINDS:
        raise HTTPException(status_code=400, detail=f"Справочник «{kind}» не является простым списком")
    return {"items": dict_db.get_entries(kind, scope, search, limit), "kind": kind, "scope": scope}