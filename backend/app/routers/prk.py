import io
import logging
import zipfile
from datetime import date
from typing import Optional
from xml.etree import ElementTree as ET

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse

from app.schemas import (
    GenerateScdRequest,
    LoadPrkRequest,
    LoadPrkResponse,
    PrkHistoryResponse,
    PrkStats,
)
from app.services.soap_client import send_load_prk
from app.services import prk_db, mis_client, settings_db, dict_db, region_match, region_links

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prk", tags=["prk"])


def _unwrap_regions(payload) -> list[dict]:
    """Достаёт список участков из ответа ЕЦП любой вложенности."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "result"):
            if key in payload:
                return _unwrap_regions(payload[key])
    return []


@router.post("/load", response_model=LoadPrkResponse)
async def load_prk(request: LoadPrkRequest):
    try:
        result = await send_load_prk(request)
    except Exception as e:
        logger.exception("Error processing LoadPrk request")
        raise HTTPException(status_code=500, detail=str(e))

    mis_save_result = None
    if result.success and request.mis_save_data:
        try:
            mis_cfg = settings_db.get_settings()
            mis_lpu_id = mis_cfg.get("misLpuId", "13003795")

            podr = request.prk_list[0].podr.strip()
            # Участки берём из локального кэша (вкладка «Справочники»). Если их
            # там нет — один раз обращаемся к ЕЦП, но результат не сохраняем:
            # загрузкой справочников управляет пользователь.
            regions = dict_db.get_regions(mis_lpu_id)
            if not regions:
                regions_resp = await mis_client.get_regions_id({"Lpu_id": mis_lpu_id, "isClose": "1"})
                regions = _unwrap_regions(regions_resp)

            # Ручная привязка важнее автоподбора: у ЕЦП и ИАС-4 разные
            # нумерации, и угадывать соответствие по названию ненадёжно.
            region, how = region_links.resolve(mis_lpu_id, podr, regions)
            if region is not None:
                logger.info("Attachment podr=%s matched region %s (%s)", podr,
                            region_match.region_value(region), how)

            if region:
                payload = request.mis_save_data.model_dump(exclude_none=True)
                payload["Lpu_id"] = mis_lpu_id
                # Server_id приходит из карты пациента; если его нет — ЛПУ из настроек.
                payload.setdefault("Server_id", mis_lpu_id)
                payload["LpuRegion_id"] = region_match.region_id(region)
                mis_save_result = await mis_client.save_person_card(payload)
                if isinstance(mis_save_result, dict) and mis_save_result.get("success") is False:
                    # Приводим к виду {success, error: "текст"}, который ждёт ResultPanel.
                    err = mis_save_result.get("error")
                    if isinstance(err, dict):
                        code = err.get("code")
                        message = err.get("message") or str(err)
                        message = f"[{code}] {message}" if code else message
                    else:
                        message = str(err)
                    mis_save_result = {"success": False, "error": message}
            else:
                mis_save_result = {
                    "success": False,
                    "error": region_links.diagnose(mis_lpu_id, podr, regions),
                }
        except Exception as e:
            logger.exception("MIS save-person-card failed")
            mis_save_result = {"success": False, "error": str(e)}

    # Историю пишем после отправки в ЕЦП: иначе результат ЕЦП в неё не
    # попадал, и его ошибки не были видны ни в истории, ни в статистике.
    prk_db.save_history(
        person=request.person.model_dump(),
        attachments=[a.model_dump() for a in request.prk_list],
        success=result.success,
        result=result.result.model_dump() if result.result else None,
        error_message=result.error_message,
        mis_save=mis_save_result,
    )

    return LoadPrkResponse(
        success=result.success,
        person=result.person,
        prk_list=result.prk_list,
        result=result.result,
        error_message=result.error_message,
        mis_save_result=mis_save_result,
    )


@router.post("/generate-scd")
async def generate_scd(req: GenerateScdRequest):
    root = ET.Element("query")
    patient = ET.SubElement(root, "patient")

    today = date.today()
    today_iso = today.isoformat()

    ET.SubElement(patient, "nrec").text = "1"
    ET.SubElement(patient, "date1").text = today_iso
    ET.SubElement(patient, "date2").text = today_iso
    ET.SubElement(patient, "fam").text = req.fam
    ET.SubElement(patient, "im").text = req.im
    ET.SubElement(patient, "ot").text = req.ot or ""
    ET.SubElement(patient, "w").text = str(req.w)
    ET.SubElement(patient, "dr").text = req.dr
    ET.SubElement(patient, "vpolis").text = str(req.vpolis)
    ET.SubElement(patient, "npolis").text = req.npolis
    ET.SubElement(patient, "doctype").text = ""
    ET.SubElement(patient, "docser").text = ""
    ET.SubElement(patient, "docnum").text = ""
    raw_snils = (req.snils or "").replace("-", "").replace(" ", "")
    if raw_snils and len(raw_snils) == 11 and raw_snils.isdigit():
        formatted_snils = f"{raw_snils[:3]}-{raw_snils[3:6]}-{raw_snils[6:9]} {raw_snils[9:]}"
    else:
        formatted_snils = req.snils or ""
    ET.SubElement(patient, "snils").text = formatted_snils
    ET.SubElement(patient, "mr").text = ""

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("QuerySCD.xml", xml_bytes)

    zip_buffer.seek(0)
    date_str = today.strftime("%d%m%Y")
    filename = f"{date_str}01.SCD"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/parse-asc")
async def parse_asc(file: UploadFile = File(...)):
    try:
        content = await file.read()
    except Exception as e:
        return {"success": False, "error": f"Ошибка чтения файла: {e}"}

    xml_content = None
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    xml_content = zf.read(name)
                    break
            if xml_content is None:
                return {"success": False, "error": "В архиве не найден XML-файл"}
    except zipfile.BadZipFile:
        import subprocess
        import tempfile
        import os

        # пробуем открыть как RAR через unrar-free
        tmpfile = None
        tmpdir = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.rar') as tmp:
                tmp.write(content)
                tmpfile = tmp.name
            # список файлов в архиве
            r_list = subprocess.run(
                ["unrar-free", "-t", tmpfile],
                capture_output=True, text=True, timeout=15,
            )
            if r_list.returncode == 0:
                for line in r_list.stdout.splitlines():
                    name = line.strip()
                    if name.lower().endswith(".xml"):
                        r = subprocess.run(
                            ["unrar-free", "-P", tmpfile, name],
                            capture_output=True, timeout=15,
                        )
                        if r.returncode == 0 and r.stdout:
                            xml_content = r.stdout if isinstance(r.stdout, bytes) else r.stdout.encode()
                        break
            if xml_content is None:
                # fallback: извлечь всё содержимое архива
                tmpdir = tempfile.mkdtemp()
                r = subprocess.run(
                    ["unrar-free", "-x", tmpfile, tmpdir],
                    capture_output=True, timeout=15,
                )
                if r.returncode == 0:
                    for root_dir, _dirs, files in os.walk(tmpdir):
                        for fname in files:
                            if fname.lower().endswith(".xml"):
                                with open(os.path.join(root_dir, fname), "rb") as fh:
                                    xml_content = fh.read()
                                break
                        if xml_content:
                            break
        except Exception:
            pass
        finally:
            for p in filter(None, [tmpfile, tmpdir]):
                try:
                    if os.path.isfile(p):
                        os.unlink(p)
                    elif os.path.isdir(p):
                        import shutil
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass

        if xml_content is None:
            file_type = "?"
            try:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(content)
                    tmpname = tmp.name
                result = subprocess.run(["file", tmpname], capture_output=True, text=True, timeout=5)
                file_type = result.stdout.strip()
                os.unlink(tmpname)
            except Exception:
                pass
            magic = content[:16].hex()
            return {"success": False, "error": f"Файл не является zip- или rar-архивом ({file_type}, magic={magic}, size={len(content)}b)"}

    try:
        # очистка от trailing-мусора после корневого элемента
        raw = xml_content
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        end_tag = raw.rfind("</")
        if end_tag > 0:
            close = raw.find(">", end_tag)
            if close > 0:
                raw = raw[: close + 1]
        root = ET.fromstring(raw.encode("utf-8"))
    except ET.ParseError as e:
        return {"success": False, "error": f"Ошибка парсинга XML: {e}"}

    ns = {"": ""}

    def text(el, path):
        found = el.find(path)
        if found is not None and found.text:
            return found.text.strip()
        return None

    query = root.find("query")
    if query is None:
        return {"success": False, "error": "XML не содержит элемент query"}

    patient = query.find("patient")
    result_el = query.find("result")

    data = {}

    if result_el is not None:
        ack_str = text(result_el, "ack")
        if ack_str is not None:
            data["ack"] = int(ack_str)

        algs = []
        for alg in result_el.findall("alg"):
            if alg.text:
                algs.append(alg.text.strip())
        if algs:
            data["algs"] = algs

        ins = result_el.find("ins")
        if ins is not None:
            insurance = {}
            for tag in ("smo", "vpolis", "fpolis", "npolis", "dvisit", "dbeg", "dend", "reason", "id", "snils", "dr", "w"):
                val = text(ins, tag)
                if val is not None:
                    if tag in ("smo", "vpolis", "fpolis", "reason", "id", "w"):
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                    insurance[tag] = val
            if insurance:
                data["insurance"] = insurance

        prk = result_el.find("prk")
        if prk is not None:
            attachment = {}
            for tag in ("typeprk", "mo", "podr", "modt", "meth"):
                val = text(prk, tag)
                if val is not None:
                    if tag in ("typeprk", "mo", "meth"):
                        try:
                            val = int(val)
                        except ValueError:
                            pass
                    attachment[tag] = val
            if attachment:
                data["attachment"] = attachment

    if not data:
        return {"success": False, "error": "Не удалось извлечь данные из XML"}

    return {"success": True, "data": data}


@router.get("/history", response_model=PrkHistoryResponse)
async def get_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    fam: Optional[str] = Query(None),
    mo: Optional[int] = Query(None),
):
    return prk_db.get_history(
        page=page,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        fam=fam,
        mo=mo,
    )


@router.get("/stats", response_model=PrkStats)
async def get_stats():
    return prk_db.get_stats()
