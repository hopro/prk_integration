"""Загрузка справочников ТФОМС из XML-выгрузок.

Формат одинаковый: ZIP (реже — сам XML) с файлом в кодировке windows-1251,
корневой элемент ``ROOT``, записи — ``<REC атрибут="значение" .../>``.

Поддерживаются выгрузки:
  SPSMO.zip        — страховые компании (СМО),   атрибуты CODE, NAME, MAIL
  SPMO.zip         — медицинские организации,     атрибуты CODE, NAME, TERR, …
  SPDEPT.xml/.zip  — подразделения ИАС-4: коды, которые ИАС принимает в podr

Файлы бывают большими, поэтому парсинг
идёт потоково, без построения дерева целиком.
"""

import csv
import io
import logging
import os
import re
import zipfile
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Значения, пригодные для поиска и отображения.
KINDS = {
    "spsmo": "Страховые компании (СМО)",
    "spmo": "Медицинские организации (СПМО)",
    "spdept": "Подразделения МО (справочник ИАС-4)",
}

# Имя файла-признак для каждого вида справочника.
FILE_MARKERS = {
    "spsmo": ("spsmo",),
    "spmo": ("spmo",),
    "spdept": ("spdept", "spmo_div", "podrazd"),
}

DEFAULT_ENCODINGS = ("cp1251", "windows-1251", "utf-8")

_CODE_RE = re.compile(r"^(\d+)")


def detect_kind(filename: str, xml_text_head: str) -> str:
    """Определяет вид справочника по имени файла, затем по содержимому.

    Имя надёжнее содержимого: в выгрузке СПМО много полей, и подразделения
    ИАС-4 легко спутать с медицинскими организациями.
    """
    lowered = filename.lower()
    for kind, markers in FILE_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return kind

    # По содержимему смотрим первую запись: в выгрузке СПМО много похожих
    # полей, и без разбора атрибутов подразделение ИАС-4 не отличить от МО.
    keys: set[str] = set()
    for match in re.finditer(r"<REC\s+([^>]+)", xml_text_head or "", re.IGNORECASE):
        keys = {k.upper() for k in re.findall(r"(\w+)\s*=", match.group(1))}
        break

    if keys and any(f in keys for f in _IAS_CODE_FIELDS) and not (
        "NAM_SPMO" in keys or "TERR" in keys or "MAIL" in keys
    ):
        return "spdept"
    if "MAIL" in keys and "TERR" not in keys:
        return "spsmo"
    return "spmo"


_DECL_ENCODING_RE = re.compile(rb"encoding\s*=\s*['\"]([\w-]+)['\"]")


def _declared_encoding(raw: bytes) -> str | None:
    """Кодировка из заголовка <?xml ... encoding="..."?>."""
    head = raw[:200]
    match = _DECL_ENCODING_RE.search(head)
    if not match:
        return None
    name = match.group(1).decode("ascii", "ignore")
    aliases = {"windows-1251": "cp1251", "utf-8": "utf-8", "utf8": "utf-8"}
    return aliases.get(name.lower(), name)


def _decode(raw: bytes, encoding_hint: str = "") -> str:
    """Раскодирует XML. Выгрузки ТФОМС приходят в windows-1251, но встречаются
    и в utf-8 — кодировку берём из заголовка самого файла."""
    declared = _declared_encoding(raw)
    order = [declared] if declared else []
    order.append(encoding_hint) if encoding_hint else None
    order += [e for e in DEFAULT_ENCODINGS if e not in order]
    for encoding in order:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # Совсем нечитаемый файл: не теряем содержимое из-за одной сбитой буквы.
    return raw.decode(DEFAULT_ENCODINGS[0], errors="replace")


def _read_payload(filename: str, raw: bytes, encoding_hint: str = "") -> tuple[str, str]:
    """Возвращает (имя xml-файла, текст). Работает и с zip, и с голым XML."""
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            if not names:
                raise ValueError("В архиве нет XML-файла")
            # Берём самый большой: в некоторых выгрузках рядом лежит служебный.
            entry = max(names, key=lambda n: archive.getinfo(n).file_size)
            payload = archive.read(entry)
        return entry, _decode(payload, encoding_hint)

    return os.path.basename(filename), _decode(raw, encoding_hint)


def _iter_records(xml_text: str):
    """Потоковый обход записей: итератор по (атрибуты)."""
    for _, element in ET.iterparse(io.StringIO(xml_text), events=("end",)):
        if element.tag.upper() == "REC":
            yield dict(element.attrib)
            element.clear()


def _mo_variants(code: str) -> list[str]:
    """Коды одной МО в разной записи: 893, 0893, 660893."""
    code = (code or "").strip()
    if not code:
        return []
    variants = [code]
    stripped = code.lstrip("0")
    if stripped and stripped != code:
        variants.append(stripped)
    return variants


def _merge_by_code(attrs_list, extra_of) -> list[dict]:
    """Один справочник — много записей на код.

    Записи с одним CODE дополняют друг друга: у СПМО по 5–6 записей на МО, и
    первая нередко приходит с пустым NAME, тогда как название есть в следующей.
    Поэтому дубликаты не отбрасываются, а дополняются: любое непустое значение
    выигрывает у пустого.
    """
    merged: dict[str, dict] = {}
    for attrs in attrs_list:
        code = (attrs.get("CODE") or "").strip()
        if not code:
            continue
        name = (attrs.get("NAME") or "").strip()
        extra = extra_of(attrs)
        row = merged.get(code)
        if row is None:
            merged[code] = {"code": code, "name": name, "extra": extra}
            continue
        if not row["name"] and name:
            row["name"] = name
        if not row["extra"] and extra:
            row["extra"] = extra
    return list(merged.values())


def parse_spsmo(xml_text: str) -> list[dict]:
    return _merge_by_code(
        _iter_records(xml_text),
        lambda a: (a.get("MAIL") or "").strip(),
    )


def parse_spmo(xml_text: str) -> list[dict]:
    def extra_of(attrs) -> str:
        terr = (attrs.get("TERR") or "").strip()
        address = (attrs.get("ADDRESS") or "").strip()
        return " ".join(filter(None, [f"терр. {terr}" if terr else "", address]))

    return _merge_by_code(_iter_records(xml_text), extra_of)


# Имена полей для справочника подразделений ИАС-4. Формат выгрузки заказчика
# неизвестен заранее, поэтому принимаем распространённые варианты написания.
# PODR идёт первым: в выгрузке ИАС-4 есть ещё и CODE — это номер подразделения
# внутри МО («14»), а не код, который принимает ИАС-4 («31400»).
_IAS_CODE_FIELDS = ("PODR", "PODR_CODE", "PODRCD", "CODE", "ID", "KOD")
_IAS_NAME_FIELDS = ("NAME", "PODRNAME", "NAMEPODR", "NAME_PODR", "TITLE", "NAIMENOVANIE")
_IAS_MO_FIELDS = ("MO", "MO_CODE", "CODE_MO", "KODMO", "LPU")


def parse_spdept(xml_text: str) -> list[dict]:
    """Подразделения ИАС-4: код podr и наименование.

    Это единственный источник кодов, которые ИАС-4 принимает в поле podr.
    Список участков ЕЦП для этой цели не годится: там своя нумерация, и все
    коды с суффиксом _ГРП (а это 40 из 107 участков) ИАС-4 отвергает с ошибкой
    501 «отсутствует в справочнике».
    """
    rows, seen = [], set()
    for attrs in _iter_records(xml_text):
        keys = {k.upper(): v for k, v in attrs.items()}
        code = ""
        for field in _IAS_CODE_FIELDS:
            if (keys.get(field) or "").strip():
                code = keys[field].strip()
                break
        if not code:
            continue
        mo = ""
        for field in _IAS_MO_FIELDS:
            if (keys.get(field) or "").strip():
                mo = keys[field].strip()
                break
        key = (mo, code)
        if key in seen:
            continue
        seen.add(key)

        # Короткое и полное названия есть по-разному: LONGNAME подробнее
        # («Терапевтический участок №6» против «Участок №6»), и именно оно
        # ближе к тому, как участок назван в ЕЦП.
        short = ""
        for field in _IAS_NAME_FIELDS:
            if (keys.get(field) or "").strip():
                short = keys[field].strip()
                break
        long_name = (keys.get("LONGNAME") or "").strip()
        name = long_name or short or code

        # DEND — до какой даты подразделение действует. По нему отсекаются
        # закрытые подразделения, которых в справочнике большинство.
        valid_until = _parse_date(keys.get("DEND") or keys.get("DATEEND") or "")

        # PRKYES — тот самый признак «разрешено прикрепление», на который ИАС-4
        # отвечает ошибкой 502.
        prkyes = (keys.get("PRKYES") or "").strip()
        allow = "" if prkyes in ("", "0") else " · прикрепление разрешено"

        rows.append({
            "code": code,
            "name": name,
            "scope": mo,                       # область = код МО
            "extra": f"КОД {code}" + (f" · {short}" if short and short != name else "") + allow,
            "valid_until": valid_until,
        })
    return rows


def _parse_date(value: str) -> str:
    """Дата из выгрузки (ДД.ММ.ГГГГ) в виде ГГГГ-ММ-ДД.

    Пустая дата означает, что подразделение не ограничено сроком: 31.12.2999 в
    выгрузке — это открытый период.
    """
    text = (value or "").strip()
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", text)
    if not match:
        return ""
    day, month, year = match.groups()
    if year == "2999":
        return "9999-12-31"
    try:
        return f"{year}-{month}-{day}"
    except ValueError:
        return ""


PARSERS = {
    "spsmo": parse_spsmo,
    "spmo": parse_spmo,
    "spdept": parse_spdept,
}


def parse_upload(filename: str, raw: bytes, encoding_hint: str = "") -> tuple[str, str, list[dict]]:
    """Разбирает загруженный zip/xml.

    Возвращает (вид справочника, кодировка, записи). Вид определяется по имени
    файла, а при его неоднозначности — по атрибутам первой записи.
    """
    entry, text = _read_payload(filename, raw, encoding_hint)

    kind = detect_kind(entry, text[:4000])
    if kind is None:
        # Имя файла бесполезно — определяем по первой записи.
        for attrs in _iter_records(text):
            keys = {k.upper() for k in attrs}
            if any(f in keys for f in _IAS_CODE_FIELDS) and not (
                "NAM_SPMO" in keys or "TERR" in keys or "MAIL" in keys
            ):
                kind = "spdept"
            elif "MAIL" in keys and "TERR" not in keys:
                kind = "spsmo"
            elif "TERR" in keys or "OGRN" in keys:
                kind = "spmo"
            break
    if kind is None:
        raise ValueError(
            "Не удалось определить вид справочника. Ожидается SPSMO.zip, "
            "SPMO.zip или SPDEPT.xml"
        )

    rows = PARSERS[kind](text)
    logger.info("Разобрано %s из %s: %s записей", entry, filename, len(rows))
    return kind, entry, rows


def parse_csv_spdept(payload: str, delimiter: str | None = None) -> list[dict]:
    """Справочник подразделений ИАС-4 из CSV.

    Формат выгрузки ИАС-4 заранее неизвестен, поэтому заголовки распознаются по
    набору синонимов, а разделитель определяется автоматически.
    """
    if delimiter is None:
        delimiter = ";" if payload.count(";") > payload.count(",") else ","
    reader = csv.DictReader(io.StringIO(payload), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV пуст или без заголовка")

    alias: dict[str, str] = {}
    for column in reader.fieldnames:
        name = (column or "").strip().lower()
        if name in [f.lower() for f in _IAS_CODE_FIELDS]:
            alias[(column or "").strip()] = "code"
        elif name in [f.lower() for f in _IAS_NAME_FIELDS]:
            alias[(column or "").strip()] = "name"
        elif name in [f.lower() for f in _IAS_MO_FIELDS]:
            alias[(column or "").strip()] = "mo"

    rows, seen = [], set()
    for raw in reader:
        item = {"code": "", "name": "", "extra": ""}
        for original, value in raw.items():
            target = alias.get((original or "").strip())
            if target == "code":
                item["code"] = (value or "").strip()
            elif target == "name":
                item["name"] = (value or "").strip()
            elif target == "mo" and (value or "").strip():
                item["extra"] = f"МО {value.strip()}"
        if not item["code"] or item["code"] in seen:
            continue
        seen.add(item["code"])
        if not item["name"]:
            item["name"] = item["code"]
        rows.append(item)
    return rows


def search_rows(rows: list[dict], search: str, limit: int = 0) -> list[dict]:
    needle = (search or "").strip().lower()
    if needle:
        rows = [
            r for r in rows
            if needle in r["name"].lower() or needle in r["code"].lower()
            or needle in r["extra"].lower()
        ]
    return rows[:limit] if limit else rows


def code_prefix(code: str) -> str | None:
    """Ведущие цифры кода подразделения — по ним группируется нагрузка."""
    match = _CODE_RE.match((code or "").strip())
    return match.group(1) if match else None


def mo_variants(code: str) -> list[str]:
    return _mo_variants(code)