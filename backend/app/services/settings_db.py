import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("SETTINGS_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "settings.db"))

# Настройки приложения. Значения по умолчанию берутся из окружения, но любые из
# них можно переопределить через шестерёнку — тогда в БД попадает то, что ввёл
# пользователь. Адреса сервисов тоже здесь: заказчик может развернуть систему на
# других адресах, не пересобирая контейнеры.
FIELDS = [
    ("user", "TEXT NOT NULL DEFAULT ''"),
    ("password", "TEXT NOT NULL DEFAULT ''"),
    ("default_mo", "TEXT NOT NULL DEFAULT '0893'"),
    ("mis_lpu_id", "TEXT NOT NULL DEFAULT ''"),
    ("mis_login", "TEXT NOT NULL DEFAULT ''"),
    ("mis_password", "TEXT NOT NULL DEFAULT ''"),
    ("ias_url", "TEXT NOT NULL DEFAULT ''"),
    ("ias_check_url", "TEXT NOT NULL DEFAULT ''"),
    ("ecp_url", "TEXT NOT NULL DEFAULT ''"),
    # Кодировка ТФОМС для файлов справочников (SPSMO.zip и т.п.).
    ("tfoms_encoding", "TEXT NOT NULL DEFAULT ''"),
]

# JSON-ключ <-> колонка БД
KEYS = [
    ("user", "user"),
    ("password", "password"),
    ("defaultMo", "default_mo"),
    ("misLpuId", "mis_lpu_id"),
    ("misLogin", "mis_login"),
    ("misPassword", "mis_password"),
    ("iasUrl", "ias_url"),
    ("iasCheckUrl", "ias_check_url"),
    ("ecpUrl", "ecp_url"),
    ("tfomsEncoding", "tfoms_encoding"),
]

# Адреса, для которых окружение служит источником значений по умолчанию.
# SOAPAction заданы протоколом ИАС-4 и всегда одинаковы, поэтому в настройках
# их нет: см. app/services/soap_client.py.
ENV_BACKED = {
    "SOAP_URL": "iasUrl",
    "SOAP_CHECK_URL": "iasCheckUrl",
    "MIS_BASE_URL": "ecpUrl",
    "TFOMS_ENCODING": "tfomsEncoding",
}


def _get_conn():
    directory = os.path.dirname(os.path.abspath(DB_PATH))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_schema(conn):
    columns = ",\n            ".join(f"{name} {decl}" for name, decl in FIELDS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            {columns}
        )
    """)
    # Добавление колонок, которых ещё нет (база создана прошлой версией).
    for name, decl in FIELDS:
        try:
            conn.execute(f"ALTER TABLE settings ADD COLUMN {name} {decl}")
        except sqlite3.OperationalError:
            pass


def _ensure_row(conn):
    """Гарантирует, что схема и строка настроек существуют.

    Вызывается и при старте, и при каждом чтении: если файл БД удалили или
    заменили на живом процессе, приложение не должно молча отдавать пустые
    настройки — иначе SOAP-обмен и сохранение в ЕЦП падают без объяснений.
    """
    _create_schema(conn)
    row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
    if row is not None:
        return False

    initial = {key: "" for key, _ in KEYS}
    initial["defaultMo"] = "0893"
    initial["misLpuId"] = "13003795"
    # Адреса подставляем сразу, чтобы первый запуск был уже рабочим.
    for env_key, field_key in ENV_BACKED.items():
        initial[field_key] = os.getenv(env_key, "")

    columns = ", ".join(dict(KEYS)[key] for key, _ in KEYS)
    placeholders = ", ".join("?" * len(KEYS))
    conn.execute(
        f"INSERT INTO settings (id, {columns}) VALUES (1, {placeholders})",
        [initial[key] for key, _ in KEYS],
    )
    return True


def init_db():
    conn = _get_conn()
    _create_schema(conn)
    created = _ensure_row(conn)

    # Пустые адреса дополняем значениями из окружения. Непустые не трогаем —
    # пользователь мог поменять их через шестерёнку.
    if not created:
        for env_key, field_key in ENV_BACKED.items():
            value = os.getenv(env_key, "")
            if not value:
                continue
            column = dict(KEYS)[field_key]
            conn.execute(
                f"UPDATE settings SET {column} = ? WHERE id = 1 AND {column} = ''", (value,)
            )

    conn.execute("UPDATE settings SET mis_lpu_id = '13003795' WHERE mis_lpu_id = ''")
    conn.commit()
    conn.close()


def get_settings() -> dict:
    conn = _get_conn()
    if _ensure_row(conn):
        conn.commit()
    columns = ", ".join(col for _, col in KEYS)
    row = conn.execute(f"SELECT {columns} FROM settings WHERE id = 1").fetchone()
    conn.close()

    result = {key: "" for key, _ in KEYS}
    if row:
        result = {key: (row[column] or "") for key, column in KEYS}
    if not result["misLpuId"]:
        result["misLpuId"] = "13003795"
    return result


def save_settings(values: dict) -> dict:
    """Записывает только переданные ключи, остальные не трогает."""
    updates = [(key, column) for key, column in KEYS if key in values]
    if not updates:
        return get_settings()

    conn = _get_conn()
    _ensure_row(conn)
    set_clause = ", ".join(f"{column} = ?" for _, column in updates)
    conn.execute(f"UPDATE settings SET {set_clause} WHERE id = 1", [values[k] for k, _ in updates])
    conn.commit()
    conn.close()
    return get_settings()


def reset_to_env_defaults() -> dict:
    """Возвращает адреса сервисов к значениям из окружения."""
    values = {key: os.getenv(env, "") for env, key in ENV_BACKED.items()}
    values["tfomsEncoding"] = values.get("tfomsEncoding") or "cp1251"
    return save_settings(values)


init_db()