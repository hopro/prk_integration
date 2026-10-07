import os
import re
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DICT_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "dictionaries.db"))

KINDS = {
    "regions": "Участки ЛПУ (ЕЦП)",
    "spmo": "Медицинские организации (СПМО)",
    "spsmo": "Страховые компании (СМО)",
    "spdept": "Подразделения МО (справочник ИАС-4)",
}

# Справочники ТФОМС: приходят XML-выгрузкой. Участки ЛПУ сюда не входят — они
# принадлежат конкретному ЛПУ и приходят только из ЕЦП.
TFOMS_KINDS = {"spmo", "spsmo", "spdept"}

# Имя файла-признак для каждого XML-справочника.
TFOMS_FILES = {
    "spsmo": "SPSMO.zip",
    "spmo": "SPMO.zip",
    "spdept": "SPDEPT.xml",
}


def _get_conn():
    # Схему готовим на первом обращении, а не только при старте сервера: иначе
    # добавление колонки не доезжает до базы, созданной прошлой версией.
    ensure_schema()
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


_initialized = False


def ensure_schema():
    """Создаёт и обновляет схему один раз за процесс.

    Раньше init_db никто не вызывал, поэтому добавление колонок (extra,
    valid_until) не доезжало до существующих баз: запись падала с
    «table dict_entries has no column named ...».
    """
    global _initialized
    if _initialized:
        return
    init_db()
    _initialized = True


def init_db():
    # Здесь _get_conn не вызывается: он сам зовёт ensure_schema.
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    # WAL позволяет читать справочники во время загрузки: разбор большого файла
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
            valid_until TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (kind, scope, code)
        );

        -- valid_until — дата, до которой запись справочника действует.
        -- В подразделениях ИАС-4 (SPDEPT) она задана явно, и по ней отсекаются
        -- закрытые подразделения: у МО 893 из 93 записей актуальны не все.
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

        -- Связь кода подразделения ИАС-4 (podr) с участком ЕЦП (LpuRegion_id).
        -- Имена участков у ЕЦП и коды подразделений у ИАС-4 — разные
        -- нумерации, и в 40 случаях из 107 участков ГП № 4 совпадения нет
        -- вовсе: все коды с суффиксом _ГРП ИАС-4 не знает. Такие пары
        -- проставляет администратор на странице «Сопоставление участков».
        -- Пустой region_id означает осознанный отказ от привязки: автоподбор
        -- больше не будет предлагать этот код.
        CREATE TABLE IF NOT EXISTS region_links (
            lpu_id      TEXT NOT NULL,
            podr        TEXT NOT NULL,
            region_id   TEXT NOT NULL DEFAULT '',
            region_name TEXT NOT NULL DEFAULT '',
            source      TEXT NOT NULL DEFAULT 'manual',
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (lpu_id, podr)
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
    if not any(row["name"] == "valid_until" for row in conn.execute("PRAGMA table_info(dict_entries)")):
        conn.execute("ALTER TABLE dict_entries ADD COLUMN valid_until TEXT NOT NULL DEFAULT ''")
    # СПФМО удалён из системы: код его записей больше не используется, но
    # в базах, где он грузился раньше, лежат 158 тысяч строк.
    stale = [kind for kind in ("spdiv",) if kind not in KINDS]
    for kind in stale:
        conn.execute("DELETE FROM dict_entries WHERE kind = ?", (kind,))
        conn.execute("DELETE FROM dict_load_log WHERE kind = ?", (kind,))
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
    """Заменяет содержимое справочника (kind, scope) целиком.

    У записи может быть своя область (`entry["scope"]`): в справочнике
    подразделений ИАС-4 область — это код МО, и подразделения разных МО лежат
    рядом. Если у записей область задана, перезаписывается весь вид справочника,
    иначе — только переданная область.
    """
    if kind not in TFOMS_KINDS:
        raise ValueError(f"Неизвестный справочник ТФОМС: {kind}")
    scope = str(scope or "").strip()
    per_entry_scope = any(str(e.get("scope") or "").strip() for e in entries)

    conn = _get_conn()
    if per_entry_scope:
        conn.execute("DELETE FROM dict_entries WHERE kind = ?", (kind,))
    else:
        conn.execute("DELETE FROM dict_entries WHERE kind = ? AND scope = ?", (kind, scope))
    now = _now()
    rows = [
        (
            kind,
            str(e.get("scope") or scope).strip(),
            str(e.get("code") or "").strip(),
            str(e.get("name") or "").strip(),
            str(e.get("extra") or "").strip(),
            now,
            str(e.get("valid_until") or "").strip(),
        )
        for e in entries
        if str(e.get("code") or "").strip()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO dict_entries "
        "(kind, scope, code, name, extra, loaded_at, valid_until) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    unique = len({(row[1], row[2]) for row in rows})
    message = f"схлопнуто повторов: {len(rows) - unique}" if unique != len(rows) else ""
    _log(conn, kind, scope, unique, source="tfoms", status="ok", message=message)
    conn.commit()
    conn.close()
    return unique


def count_entries(
    kind: str,
    scope: str = "",
    search: str = "",
    mo: str = "",
    valid_from: str = "",
) -> int:
    """Сколько записей подходит под фильтр. Считается тем же запросом, что и
    выборка, иначе счётчик на странице расходился бы с таблицей."""
    where, params = _entry_filters(kind, scope, search, mo, valid_from)
    conn = _get_conn()
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM dict_entries {where}", params
    ).fetchone()["n"]
    conn.close()
    return int(total)


def get_entries(
    kind: str,
    scope: str = "",
    search: str = "",
    limit: int = 0,
    offset: int = 0,
    mo: str = "",
    valid_from: str = "",
) -> list[dict]:
    where, params = _entry_filters(kind, scope, search, mo, valid_from)
    sql = (
        "SELECT code, name, extra, scope, loaded_at, valid_until FROM dict_entries "
        f"{where} ORDER BY name"
    )
    if limit:
        sql += " LIMIT ? OFFSET ?"
        params = params + [int(limit), max(0, int(offset))]
    conn = _get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _entry_filters(
    kind: str,
    scope: str,
    search: str,
    mo: str = "",
    valid_from: str = "",
) -> tuple[str, list]:
    """Общие условия выборки для подсчёта и для выдачи страницы.

    Поиск идёт по коду, названию и дополнительному полю; в справочнике
    подразделений ИАС-4 по mo отбираются подразделения одного МО.
    """
    where = "WHERE kind = ?"
    params: list = [kind]
    if scope:
        # Пустая область означает «любая»: у подразделений ИАС-4 областью служит
        # код МО, и спрашивать надо по конкретному МО, а не по всем сразу.
        where += " AND scope = ?"
        params.append(str(scope).strip())
    if search:
        where += " AND (code LIKE ? OR name LIKE ? OR extra LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if valid_from:
        # Подразделения ИАС-4 имеют срок действия: закрытые в выгрузке остаются,
        # но ИАС-4 их больше не принимает. Записи без срока считаем действующими.
        where += " AND (valid_until = '' OR valid_until >= ?)"
        params.append(valid_from)
    return where, params


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
    """Записывает неудачную загрузку. Ошибки записи не поднимаем: иначе
    сообщение в журнале загрузок маскирует ту ошибку, которую мы разбираем."""
    try:
        conn = _get_conn()
        _log(conn, kind, scope, 0, source, "error", message[:1000])
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"Не удалось записать в журнал загрузок: {e}")


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

        # У подразделений ИАС-4 область — код МО, и медицинских организаций в
        # выгрузке много. В интерфейсе справочник один, поэтому показываем одну
        # строку с общим числом записей; число МО идёт в подпись.
        total_rows = sum(row["rows_loaded"] for _scope, row in matching)
        last_loaded = max(row["loaded_at"] for _scope, row in matching if row["loaded_at"]) \
            if any(row["loaded_at"] for _scope, row in matching) else None
        if len(matching) > 1:
            scope_label = f"{len(matching)} МО"
        else:
            scope_label = f"МО {matching[0][0]}" if matching[0][0] else "все МО"
        result.append({
            "kind": kind, "title": title, "scope": "",
            "scopeLabel": scope_label, "rows": total_rows,
            "loadedAt": last_loaded, "source": "tfoms",
        })
    return result


# --------------------------------------------- сопоставление ИАС-4 ↔ ЕЦП

def get_region_links(lpu_id: str) -> dict[str, dict]:
    """Привязки подразделений ИАС-4 к участкам ЕЦП: код → строка привязки."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT podr, region_id, region_name, source, updated_at "
        "FROM region_links WHERE lpu_id = ?",
        (str(lpu_id or "").strip(),),
    ).fetchall()
    conn.close()
    return {r["podr"]: dict(r) for r in rows}


def save_region_link(
    lpu_id: str,
    podr: str,
    region_id: str,
    region_name: str,
    source: str = "manual",
) -> None:
    """Привязывает код подразделения ИАС-4 к участку ЕЦП.

    Пустой region_id снимает привязку, но оставляет пометку: автоподбор не
    станет снова предлагать этот код, пока администратор не решит иначе.
    """
    lpu_id = str(lpu_id or "").strip()
    podr = str(podr or "").strip()
    if not lpu_id or not podr:
        raise ValueError("Нужны Lpu_id и код подразделения")
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO region_links "
        "(lpu_id, podr, region_id, region_name, source, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            lpu_id,
            podr,
            str(region_id or "").strip(),
            str(region_name or "").strip(),
            source if region_id else "unlinked",
            _now(),
        ),
    )
    conn.commit()
    conn.close()


def save_region_links(lpu_id: str, links: list[dict], source: str = "auto") -> int:
    """Массовое сохранение привязок (используется для применения автоподбора)."""
    lpu_id = str(lpu_id or "").strip()
    if not lpu_id:
        raise ValueError("Не указан Lpu_id")
    now = _now()
    rows = [
        (
            lpu_id,
            str(item.get("podr") or "").strip(),
            str(item.get("region_id") or "").strip(),
            str(item.get("region_name") or "").strip(),
            str(item.get("source") or source),
            now,
        )
        for item in links
        if str(item.get("podr") or "").strip()
    ]
    conn = _get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO region_links "
        "(lpu_id, podr, region_id, region_name, source, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    _log(conn, "region_links", lpu_id, len(rows), source=source, status="ok")
    conn.commit()
    conn.close()
    return len(rows)


def delete_region_link(lpu_id: str, podr: str) -> int:
    """Убирает привязку целиком: код снова попадёт в автоподбор."""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM region_links WHERE lpu_id = ? AND podr = ?",
        (str(lpu_id or "").strip(), str(podr or "").strip()),
    )
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    return removed

