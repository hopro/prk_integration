import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DICT_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "dictionaries.db"))

KINDS = {
    "regions": "Участки ЛПУ (ЕЦП)",
    "spmo": "Медицинские организации (СПМО)",
    "spsmo": "Страховые компании (СМО)",
    "spdiv": "Подразделения МО (СПФМО-подразделения)",
    "spdept": "Подразделения МО (справочник ИАС-4)",
}

# Справочники ТФОМС: приходят XML-выгрузкой. Участки ЛПУ сюда не входят — они
# принадлежат конкретному ЛПУ и приходят только из ЕЦП.
TFOMS_KINDS = {"spmo", "spsmo", "spdiv", "spdept"}

# Имя файла-признак для каждого XML-справочника.
TFOMS_FILES = {
    "spsmo": "SPSMO.zip",
    "spmo": "SPMO.zip",
    "spdiv": "SPFMODIVISION.zip",
    "spdept": "SPDEPT.xml",
}


def _get_conn():
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    if directory:
        os.makedirs(directory, exist_ok=True)
    # timeout — ждать освобождения блокировки, а не падать «database is locked».
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = _get_conn()
    # WAL позволяет читать справочники во время загрузки: загрузка SPFMODIVISION
    # идёт несколько секунд, и интерфейс в это время не должен получать ошибки.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dict_entries (
            kind      TEXT NOT NULL,
            scope     TEXT NOT NULL DEFAULT '',
            code      TEXT NOT NULL,
            name      TEXT NOT NULL DEFAULT '',
            extra     TEXT NOT NULL DEFAULT '',
            loaded_at TEXT NOT NULL,
            PRIMARY KEY (kind, scope, code)
        );

        CREATE TABLE IF NOT EXISTS dict_regions (
            lpu_id           TEXT NOT NULL,
            region_id        TEXT NOT NULL,
            name             TEXT NOT NULL DEFAULT '',
            descr            TEXT NOT NULL DEFAULT '',
            med_personal_fio TEXT NOT NULL DEFAULT '',
            beg_date         TEXT NOT NULL DEFAULT '',
            end_date         TEXT NOT NULL DEFAULT '',
            sync_status      TEXT NOT NULL DEFAULT '',
            loaded_at        TEXT NOT NULL,
            PRIMARY KEY (lpu_id, region_id)
        );

        CREATE TABLE IF NOT EXISTS dict_load_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kind        TEXT NOT NULL,
            scope       TEXT NOT NULL DEFAULT '',
            rows_loaded INTEGER NOT NULL DEFAULT 0,
            source      TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT '',
            message     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_dict_entries_kind ON dict_entries (kind, scope);
        CREATE INDEX IF NOT EXISTS idx_dict_entries_name ON dict_entries (name);
    """)
    # Колонка extra появилась вместе с XML-выгрузками ТФОМС; в базах, созданных
    # прошлой версией, её нет.
    if not any(row["name"] == "extra" for row in conn.execute("PRAGMA table_info(dict_entries)")):
        conn.execute("ALTER TABLE dict_entries ADD COLUMN extra TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- участки (ЕЦП)

def save_regions(lpu_id: str, regions: list[dict]) -> int:
    """Заменяет список участков для указанного ЛПУ. Возвращает число записей.

    ЕЦП отдаёт по строке на каждое подразделение, поэтому один и тот же
    LpuRegion_id встречается многократно. Ключ таблицы — (lpu_id, region_id),
    так что дубликаты схлопываются; возвращается уже число сохранённых записей.
    """
    lpu_id = str(lpu_id or "").strip()
    if not lpu_id:
        raise ValueError("Не указан Lpu_id")

    conn = _get_conn()
    conn.execute("DELETE FROM dict_regions WHERE lpu_id = ?", (lpu_id,))
    now = _now()
    rows = [
        (
            lpu_id,
            str(r.get("LpuRegion_id") or "").strip(),
            str(r.get("LpuRegion_Name") or "").strip(),
            str(r.get("LpuRegion_Descr") or "").strip(),
            str(r.get("MedPersonal_FIO") or "").strip(),
            str(r.get("LpuRegion_begDate") or "").strip(),
            str(r.get("LpuRegion_endDate") or "").strip(),
            str(r.get("syncStatus") or "").strip(),
            now,
        )
        for r in regions
        if str(r.get("LpuRegion_id") or "").strip()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO dict_regions "
        "(lpu_id, region_id, name, descr, med_personal_fio, beg_date, end_date, sync_status, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    unique = len({row[1] for row in rows})
    message = ""
    if len(rows) != len(regions):
        message = f"без идентификатора пропущено: {len(regions) - len(rows)}"
    if unique != len(rows):
        message = (message + "; " if message else "") + f"схлопнуто повторов ЕЦП: {len(rows) - unique}"
    _log(conn, "regions", lpu_id, unique, source="ecp", status="ok", message=message)
    conn.commit()
    conn.close()
    return unique


def get_regions(lpu_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT region_id, name, descr, med_personal_fio, beg_date, end_date, sync_status, loaded_at "
        "FROM dict_regions WHERE lpu_id = ? ORDER BY name",
        (str(lpu_id or "").strip(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def region_scopes() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT lpu_id, COUNT(*) AS rows_loaded, MAX(loaded_at) AS loaded_at "
        "FROM dict_regions GROUP BY lpu_id ORDER BY lpu_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------- справочники ТФОМС

def save_entries(kind: str, scope: str, entries: list[dict]) -> int:
    """Заменяет содержимое справочника (kind, scope) целиком."""
    if kind not in TFOMS_KINDS:
        raise ValueError(f"Неизвестный справочник ТФОМС: {kind}")
    scope = str(scope or "").strip()

    conn = _get_conn()
    conn.execute("DELETE FROM dict_entries WHERE kind = ? AND scope = ?", (kind, scope))
    now = _now()
    rows = [
        (kind, scope, str(e.get("code") or "").strip(), str(e.get("name") or "").strip(),
         str(e.get("extra") or "").strip(), now)
        for e in entries
        if str(e.get("code") or "").strip()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO dict_entries (kind, scope, code, name, extra, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    unique = len({row[2] for row in rows})
    message = f"схлопнуто повторов: {len(rows) - unique}" if unique != len(rows) else ""
    _log(conn, kind, scope, unique, source="tfoms", status="ok", message=message)
    conn.commit()
    conn.close()
    return unique


def get_entries(kind: str, scope: str = "", search: str = "", limit: int = 0) -> list[dict]:
    conn = _get_conn()
    sql = "SELECT code, name, extra, scope, loaded_at FROM dict_entries WHERE kind = ? AND scope = ?"
    params: list = [kind, str(scope or "").strip()]
    if search:
        sql += " AND (code LIKE ? OR name LIKE ? OR extra LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    sql += " ORDER BY name"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def entry_scopes() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT kind, scope, COUNT(*) AS rows_loaded, MAX(loaded_at) AS loaded_at "
        "FROM dict_entries GROUP BY kind, scope ORDER BY kind, scope"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ журнал

def _log(conn, kind: str, scope: str, rows: int, source: str, status: str, message: str = ""):
    conn.execute(
        "INSERT INTO dict_load_log (kind, scope, rows_loaded, source, status, message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, scope, rows, source, status, message, _now()),
    )


def log_failure(kind: str, scope: str, source: str, message: str):
    conn = _get_conn()
    _log(conn, kind, scope, 0, source, "error", message[:1000])
    conn.commit()
    conn.close()


def load_log(limit: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT kind, scope, rows_loaded, source, status, message, created_at "
        "FROM dict_load_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ статус

def status() -> list[dict]:
    """Сводка по всем справочникам для интерфейса."""
    regions = {r["lpu_id"]: r for r in region_scopes()}
    entries = {(r["kind"], r["scope"]): r for r in entry_scopes()}

    result = []
    for kind, title in KINDS.items():
        if kind == "regions":
            if not regions:
                result.append({
                    "kind": kind, "title": title, "scope": "", "scopeLabel": "не загружен",
                    "rows": 0, "loadedAt": None, "source": "ecp",
                })
            for lpu_id, row in regions.items():
                result.append({
                    "kind": kind, "title": title, "scope": lpu_id,
                    "scopeLabel": f"Lpu_id {lpu_id}", "rows": row["rows_loaded"],
                    "loadedAt": row["loaded_at"], "source": "ecp",
                })
            continue

        # Ключи entries — кортежи (kind, scope), поэтому вид сверяем явно.
        matching = [(scope, row) for (entry_kind, scope), row in entries.items() if entry_kind == kind]
        if not matching:
            result.append({
                "kind": kind, "title": title, "scope": "", "scopeLabel": "не загружен",
                "rows": 0, "loadedAt": None, "source": "tfoms",
            })
            continue
        for scope, row in matching:
            result.append({
                "kind": kind, "title": title, "scope": scope, "scopeLabel": "все МО",
                "rows": row["rows_loaded"], "loadedAt": row["loaded_at"], "source": "tfoms",
            })
    return result


# ------------------------------------------------- участки с названиями СПФМО

def get_regions_named(lpu_id: str) -> list[dict]:
    """Участки ЛПУ с названиями из СПФМО.

    Код подразделения в ИАС-4 — это имя участка ЕЦП (`21100`, `31400_ГП3`),
    поэтому источником кодов остаётся сам ЕЦП. Человеческие названия берём из
    SPFMODIVISION: у ЕЦП часть участков названа текстом с кодом в конце
    («ОВП п. Первомайский 233100_ГРП»), а в СПФМО — без кода.
    """
    from app.services.region_match import normalize

    regions = get_regions(lpu_id)
    if not regions:
        return []

    names = {normalize(r["name"]): r["name"] for r in get_entries("spdiv") if r["name"]}
    for region in regions:
        region["division"] = (names.get(normalize(region["name"])) or region.get("descr") or "")
    return regions


init_db()