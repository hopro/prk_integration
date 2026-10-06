import os
import json
import sqlite3
import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("PRK_HISTORY_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "prk_history.db"))


def _get_conn():
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prk_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            success INTEGER NOT NULL,
            error_message TEXT,

            fam TEXT NOT NULL,
            im TEXT NOT NULL,
            ot TEXT NOT NULL DEFAULT '',
            dr TEXT NOT NULL,
            vpolis INTEGER NOT NULL,
            npolis TEXT NOT NULL,

            ack INTEGER,
            timeoper TEXT,
            errors_json TEXT,
            -- Результат отправки в ЕЦП: раньше он нигде не сохранялся, и
            -- ошибки ЕЦП («String should have at most 8 characters» и подобные)
            -- не были видны ни в истории, ни в статистике.
            mis_save_json TEXT
        );

        CREATE TABLE IF NOT EXISTS prk_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER NOT NULL REFERENCES prk_history(id),
            typeprk INTEGER NOT NULL,
            mo INTEGER NOT NULL,
            podr TEXT NOT NULL,
            dbeg TEXT NOT NULL,
            meth INTEGER NOT NULL
        );
    """)
    # Колонка появилась вместе с сохранением результата ЕЦП; в базах, созданных
    # прошлой версией, её нет.
    if not any(row["name"] == "mis_save_json" for row in conn.execute("PRAGMA table_info(prk_history)")):
        conn.execute("ALTER TABLE prk_history ADD COLUMN mis_save_json TEXT")
    conn.commit()
    conn.close()


def save_history(
    person: dict,
    attachments: list[dict],
    success: bool,
    result: Optional[dict],
    error_message: Optional[str],
    mis_save: Optional[dict] = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO prk_history (success, error_message, fam, im, ot, dr, vpolis, npolis,
                                   ack, timeoper, errors_json, mis_save_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(success),
            error_message,
            person["fam"],
            person["im"],
            person.get("ot", ""),
            str(person["dr"]),
            person["vpolis"],
            person["npolis"],
            result["ack"] if result else None,
            result["timeoper"].isoformat() if result and result.get("timeoper") else None,
            json.dumps([e.model_dump() if hasattr(e, "model_dump") else e for e in result["errors"]], ensure_ascii=False, default=str) if result and result.get("errors") else None,
            json.dumps(mis_save, ensure_ascii=False, default=str) if mis_save else None,
        ),
    )
    history_id = cur.lastrowid

    for a in attachments:
        conn.execute(
            "INSERT INTO prk_attachments (history_id, typeprk, mo, podr, dbeg, meth) VALUES (?, ?, ?, ?, ?, ?)",
            (
                history_id,
                a["typeprk"],
                a["mo"],
                a["podr"],
                str(a["dbeg"]),
                a["meth"],
            ),
        )

    conn.commit()
    conn.close()
    return history_id


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_history(
    page: int = 1,
    limit: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    fam: Optional[str] = None,
    mo: Optional[int] = None,
) -> dict:
    conn = _get_conn()
    conditions = []
    params: list = []

    if date_from:
        conditions.append("h.created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("h.created_at <= ?")
        params.append(date_to + " 23:59:59")
    if fam:
        conditions.append("(h.fam LIKE ? OR h.im LIKE ? OR h.ot LIKE ?)")
        like = f"%{fam}%"
        params.extend([like, like, like])
    if mo:
        conditions.append("EXISTS (SELECT 1 FROM prk_attachments a WHERE a.history_id = h.id AND a.mo = ?)")
        params.append(mo)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) FROM prk_history h{where}", params).fetchone()[0]

    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT h.* FROM prk_history h{where} ORDER BY h.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    items = []
    for row in rows:
        item = _row_to_dict(row)
        item["attachments"] = []
        att_rows = conn.execute(
            "SELECT * FROM prk_attachments WHERE history_id = ? ORDER BY id",
            (item["id"],),
        ).fetchall()
        for att in att_rows:
            item["attachments"].append(_row_to_dict(att))
        item["success"] = bool(item["success"])
        item["vpolis"] = int(item["vpolis"])
        if item["errors_json"]:
            try:
                item["errors"] = json.loads(item["errors_json"])
            except (json.JSONDecodeError, TypeError):
                item["errors"] = []
        else:
            item["errors"] = []
        # Результат отправки в ЕЦП: успех либо текст ошибки.
        if item.get("mis_save_json"):
            try:
                item["misSave"] = json.loads(item["mis_save_json"])
            except (json.JSONDecodeError, TypeError):
                item["misSave"] = None
        else:
            item["misSave"] = None
        item.pop("errors_json", None)
        item.pop("mis_save_json", None)
        items.append(item)

    conn.close()
    return {"items": items, "total": total, "page": page, "limit": limit}


def get_stats() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM prk_history").fetchone()[0]
    success = conn.execute("SELECT COUNT(*) FROM prk_history WHERE success = 1").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM prk_history WHERE success = 0").fetchone()[0]

    # Сколько дошло до ЕЦП и с каким результатом. Отдельно от success: запись
    # может успешно уйти в ИАС-4 и при этом не отправиться в ЕЦП.
    ecp_attempted = conn.execute(
        "SELECT COUNT(*) FROM prk_history WHERE mis_save_json IS NOT NULL"
    ).fetchone()[0]
    ecp_ok = conn.execute(
        "SELECT COUNT(*) FROM prk_history WHERE mis_save_json LIKE '%\"success\": true%'"
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "ecpAttempted": ecp_attempted,
        "ecpSuccess": ecp_ok,
        "ecpFailed": max(0, ecp_attempted - ecp_ok),
    }


init_db()
