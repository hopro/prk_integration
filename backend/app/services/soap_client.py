import os
import logging
from xml.etree import ElementTree as ET
from datetime import date, datetime

import httpx
from defusedxml import ElementTree as DefusedET

from app.schemas import (
    LoadPrkRequest,
    LoadPrkResponse,
    PersonSchema,
    AttachmentSchema,
    ResultSchema,
    ErrorSchema,
    InsCheckRequest,
    InsCheckResponse,
    InsCheckError,
    InsuranceInfo,
    CheckPrkInfo,
)

logger = logging.getLogger(__name__)

# SOAPAction — часть контракта ИАС-4, они всегда одинаковы, поэтому в настройках
# их нет. Адреса сервисов, наоборот, меняются от развёртывания к развёртыванию.
LOADPRK_ACTION = "http://tfoms.e-burg.ru/srv_loadprk/LoadPrk"
GETINSPRKSTATE_ACTION = "http://tempuri.org/GetInsPrkState"


def _soap_config() -> dict[str, str]:
    """Адреса ИАС берём из настроек (их можно менять через шестерёнку),
    с откатом на переменные окружения."""
    from app.services.settings_db import get_settings

    stored = get_settings()
    return {
        "url": stored.get("iasUrl") or os.getenv("SOAP_URL", "http://localhost/IASWeb/LoadPrk/LoadPrk.asmx"),
        "action": LOADPRK_ACTION,
        "checkUrl": stored.get("iasCheckUrl") or os.getenv("SOAP_CHECK_URL", "http://localhost/IASWeb/InsCheck/InsCheck.asmx"),
        "checkAction": GETINSPRKSTATE_ACTION,
    }


SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <LoadPrk xmlns="http://tfoms.e-burg.ru/srv_loadprk/">
      {query_xml}
    </LoadPrk>
  </soap:Body>
</soap:Envelope>"""


def _build_query_xml(req: LoadPrkRequest) -> str:
    query = ET.Element("query")

    login = ET.SubElement(query, "login")
    ET.SubElement(login, "user").text = req.login.user
    ET.SubElement(login, "password").text = req.login.password

    person = ET.SubElement(query, "person")
    ET.SubElement(person, "fam").text = req.person.fam
    ET.SubElement(person, "im").text = req.person.im
    ET.SubElement(person, "ot").text = req.person.ot
    ET.SubElement(person, "dr").text = req.person.dr.isoformat()
    ET.SubElement(person, "vpolis").text = str(req.person.vpolis)
    ET.SubElement(person, "npolis").text = req.person.npolis

    for a in req.prk_list:
        prk = ET.SubElement(query, "prk")
        ET.SubElement(prk, "typeprk").text = str(a.typeprk)
        ET.SubElement(prk, "mo").text = str(a.mo)
        ET.SubElement(prk, "podr").text = a.podr
        ET.SubElement(prk, "dbeg").text = a.dbeg.isoformat()
        ET.SubElement(prk, "meth").text = str(a.meth)

    return ET.tostring(query, encoding="unicode")


def _parse_answer(xml_str: str) -> LoadPrkResponse:
    root = DefusedET.fromstring(xml_str)
    answer = _unwrap_answer(root)

    person_el = answer.find("person")
    person = PersonSchema(
        fam=_text(person_el, "fam"),
        im=_text(person_el, "im"),
        ot=_text(person_el, "ot"),
        dr=_text(person_el, "dr"),
        vpolis=int(_text(person_el, "vpolis")),
        npolis=_text(person_el, "npolis"),
    )

    prk_list: list[AttachmentSchema] = []
    for prk_el in answer.findall("prk"):
        prk_list.append(
            AttachmentSchema(
                typeprk=int(_text(prk_el, "typeprk")),
                mo=int(_text(prk_el, "mo")),
                podr=_text(prk_el, "podr"),
                dbeg=_text(prk_el, "dbeg"),
                meth=int(_text(prk_el, "meth")),
            )
        )

    result_el = answer.find("result")
    result = None
    if result_el is not None:
        errors: list[ErrorSchema] = []
        for err_el in result_el.findall("err"):
            errors.append(
                ErrorSchema(
                    errcode=int(_text(err_el, "errcode")),
                    errname=_text(err_el, "errname"),
                    comment=_text(err_el, "comment"),
                )
            )
        ack_val = int(_text(result_el, "ack"))
        result = ResultSchema(
            timeoper=datetime.fromisoformat(_text(result_el, "timeoper")),
            ack=ack_val,
            errors=errors,
        )

    return LoadPrkResponse(
        success=result is not None and result.ack == 0,
        person=person,
        prk_list=prk_list,
        result=result,
        error_message=None,
    )


def _strip_ns(element: ET.Element) -> ET.Element:
    element.tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
    for child in element:
        _strip_ns(child)
    return element


def _text(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    if el is not None and el.text is not None:
        return el.text
    return ""


async def send_load_prk(req: LoadPrkRequest) -> LoadPrkResponse:
    config = _soap_config()
    query_xml = _build_query_xml(req)
    body = SOAP_TEMPLATE.format(query_xml=query_xml)

    logger.info("Sending LoadPrk SOAP request to %s", config["url"])
    logger.debug("SOAP request body: %s", body)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": config["action"],
    }

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        response = await client.post(config["url"], content=body.encode("utf-8"), headers=headers)

    logger.info("SOAP response status: %s", response.status_code)
    logger.debug("SOAP response body: %s", response.text)

    if response.status_code != 200:
        body = response.text
        if body.strip().startswith("<"):
            is_html = body.strip().startswith("<!DOCTYPE html") or body.strip().startswith("<html")
        else:
            is_html = False

        hint = ""
        if is_html:
            hint = "Сервис вернул HTML-страницу вместо SOAP-ответа. Проверьте адрес ИАС в настройках (шестерёнка → «Адреса сервисов»)."
        else:
            hint = f"SOAP сервис вернул HTTP {response.status_code}."

        return LoadPrkResponse(
            success=False,
            person=req.person,
            prk_list=req.prk_list,
            result=None,
            error_message=f"{hint} Тело ответа: {body[:500]}",
        )

    text = response.text.strip()
    if not text.startswith("<?xml") and not text.startswith("<"):
        return LoadPrkResponse(
            success=False,
            person=req.person,
            prk_list=req.prk_list,
            result=None,
            error_message=f"Сервис вернул не XML. Проверьте адрес ИАС в настройках. Ответ: {text[:500]}",
        )

    try:
        return _parse_answer(text)
    except Exception as e:
        logger.exception("Failed to parse SOAP response")
        return LoadPrkResponse(
            success=False,
            person=req.person,
            prk_list=req.prk_list,
            result=None,
            error_message=f"Ошибка разбора ответа SOAP: {e}",
        )


CHECK_SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetInsPrkState xmlns="http://tempuri.org/">
      {query_xml}
    </GetInsPrkState>
  </soap:Body>
</soap:Envelope>"""


def _build_check_query_xml(req: InsCheckRequest) -> str:
    query = ET.Element("query")
    login = ET.SubElement(query, "login")
    ET.SubElement(login, "user").text = req.login.user
    ET.SubElement(login, "password").text = req.login.password
    ET.SubElement(query, "nrec").text = req.nrec
    ET.SubElement(query, "date1").text = req.date1.isoformat()
    ET.SubElement(query, "date2").text = req.date2.isoformat()
    ET.SubElement(query, "type_org").text = str(req.type_org)
    ET.SubElement(query, "code_org").text = str(req.code_org)

    def _tag(parent: ET.Element, tag: str, val: str) -> None:
        ET.SubElement(parent, tag).text = val

    _tag(query, "fam", req.fam)
    _tag(query, "im", req.im)
    _tag(query, "ot", req.ot)
    _tag(query, "w", str(req.w) if req.w is not None else "")
    _tag(query, "dr", req.dr.isoformat() if req.dr else "")
    _tag(query, "vpolis", str(req.vpolis) if req.vpolis is not None else "")
    _tag(query, "npolis", req.npolis)
    _tag(query, "doctype", str(req.doctype) if req.doctype is not None else "")
    _tag(query, "docser", req.docser)
    _tag(query, "docnum", req.docnum)
    _tag(query, "snils", req.snils)
    _tag(query, "mr", req.mr)

    return ET.tostring(query, encoding="unicode")


def _unwrap_answer(root: ET.Element) -> ET.Element:
    _strip_ns(root)
    for tag in ("Body", "GetInsPrkStateResponse", "GetInsPrkStateResult", "LoadPrkResponse", "LoadPrkResult"):
        found = root.find(f".//{tag}")
        if found is not None:
            root = found
    ans = root.find(".//answer")
    if ans is not None:
        return ans
    return root


def _parse_check_answer(xml_str: str) -> InsCheckResponse:
    root = DefusedET.fromstring(xml_str)

    answer = _unwrap_answer(root)

    nrec = _text(answer, "nrec")
    ack_str = _text(answer, "ack")
    ack = int(ack_str) if ack_str else 2

    errors: list[InsCheckError] = []
    for err_el in answer.findall("err"):
        errors.append(InsCheckError(
            errcode=int(_text(err_el, "errcode")),
            errtext=_text(err_el, "errtext"),
        ))

    algs: list[str] = []
    for alg_el in answer.findall("alg"):
        if alg_el.text and alg_el.text.strip():
            algs.append(alg_el.text.strip())

    ins_el = answer.find("ins")
    insurance = None
    if ins_el is not None:
        insurance = InsuranceInfo(
            smo=_int_or_none(_text(ins_el, "smo")),
            vpolis=_int_or_none(_text(ins_el, "vpolis")),
            fpolis=_int_or_none(_text(ins_el, "fpolis")),
            npolis=_text(ins_el, "npolis"),
            dvisit=_date_or_none(_text(ins_el, "dvisit")),
            dbeg=_date_or_none(_text(ins_el, "dbeg")),
            dend=_date_or_none(_text(ins_el, "dend")),
            reason=_int_or_none(_text(ins_el, "reason")),
            id=_int_or_none(_text(ins_el, "id")),
        )

    prk_el = answer.find("prk")
    attachment = None
    if prk_el is not None and prk_el.find("mo") is not None:
        attachment = CheckPrkInfo(
            mo=_int_or_none(_text(prk_el, "mo")),
            modt=_date_or_none(_text(prk_el, "modt")),
            podr=_text(prk_el, "podr"),
        )

    return InsCheckResponse(
        success=ack == 0,
        nrec=nrec,
        ack=ack,
        errors=errors,
        algs=algs,
        insurance=insurance,
        attachment=attachment,
        p_disp=_text(answer, "p_disp"),
        p_proph=_text(answer, "p_proph"),
        p_healthc=_text(answer, "p_healthc"),
        error_message=None,
    )


def _int_or_none(val: str) -> int | None:
    if val and val.strip():
        try:
            return int(val)
        except ValueError:
            pass
    return None


def _date_or_none(val: str) -> date | None:
    if val and val.strip():
        try:
            from datetime import date as d_date
            parts = val.strip().split("-")
            return d_date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            pass
    return None


async def send_get_ins_prk_state(req: InsCheckRequest) -> InsCheckResponse:
    config = _soap_config()
    query_xml = _build_check_query_xml(req)
    body = CHECK_SOAP_TEMPLATE.format(query_xml=query_xml)

    logger.info("Sending GetInsPrkState SOAP request to %s", config["checkUrl"])
    logger.info("GetInsPrkState request XML: %s", query_xml[:2000])

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": config["checkAction"],
    }

    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        response = await client.post(config["checkUrl"], content=body.encode("utf-8"), headers=headers)

    logger.info("SOAP response status: %s", response.status_code)
    logger.debug("SOAP response body: %s", response.text[:2000])

    if response.status_code != 200:
        body_text = response.text
        is_html = body_text.strip().startswith("<!DOCTYPE html") or body_text.strip().startswith("<html")
        hint = "Сервис вернул HTML-страницу. Проверьте адрес ИАС (проверка полиса) в настройках." if is_html else f"HTTP {response.status_code}."
        return InsCheckResponse(
            success=False, nrec=req.nrec, ack=2, errors=[],
            error_message=f"{hint} Тело ответа: {body_text[:500]}",
        )

    text = response.text.strip()
    if not text.startswith("<?xml") and not text.startswith("<"):
        return InsCheckResponse(
            success=False, nrec=req.nrec, ack=2, errors=[],
            error_message=f"Сервис вернул не XML. Проверьте адрес ИАС (проверка полиса) в настройках. Ответ: {text[:500]}",
        )

    try:
        logger.info("Raw SOAP response: %s", text[:2000])
        return _parse_check_answer(text)
    except Exception as e:
        logger.exception("Failed to parse InsCheck SOAP response")
        return InsCheckResponse(
            success=False, nrec=req.nrec, ack=2, errors=[],
            error_message=f"Ошибка разбора ответа SOAP: {e}",
        )
