#!/usr/bin/env python3
"""Дымовой тест API prk_integration backend.

Проверяет, что каждый маршрут отвечает без 5xx. Нужен, потому что маршруты
изменяются вручную, а несовпадение импортов (например, `settings_db.` при
переведённом на `from ... import get_settings`) даёт 500 только в рантайме —
импорт модуля при этом проходит успешно.

Тест НЕ разрушающий: `POST /api/settings` сначала читает текущие настройки и
записывает их же обратно, поэтому рабочие учётные данные ИАС-4 не подменяются.

Запуск (по умолчанию — через интерфейс, порт 3001):
    python3 backend/smoke_test.py [http://127.0.0.1:3001]

Порт backend на хост не публикуется: снаружи доступен только интерфейс,
а он проксирует /api на backend. Проверять надо именно так, как проверяет
пользователь.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3001"


def call(method: str, path: str, body: dict | None, full: bool = False) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    # Кириллица в query-параметрах требует percent-encoding: иначе urllib
    # падает с UnicodeEncodeError ещё до отправки запроса.
    target = urllib.parse.quote(f"{BASE}{path}", safe=":/?&=%")
    req = urllib.request.Request(
        target,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    limit = 1 << 20 if full else 80
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()[:limit].decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:limit].decode(errors="replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def read_settings() -> dict:
    # Запрашиваем includeMisStatus: адрес ЕЦП и учётные данные — источник правды
    # на шлюзе, и без этого параметра проверялось бы только локальное зеркало.
    _, raw = call("GET", "/api/settings?includeMisStatus=true", None, full=True)
    try:
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"не удалось разобрать ответ /api/settings: {e}") from e


# Пустые поля ЕЦП обязаны давать 400, а не 5xx и не молча портить настройки.
STATIC_CHECKS = [
    ("GET", "/api/health", None),
    ("GET", "/api/settings?includeMisStatus=true", None),
    ("GET", "/api/v1/auth/mis-credentials", None),
    ("GET", "/api/v1/auth/mis-config", None),
    ("GET", "/api/v1/auth/gateway-health", None),
    ("GET", "/api/dict", None),
    ("GET", "/api/dict/spdept", None),
    ("GET", "/api/dict/spdept?search=ФАП", None),
    ("GET", "/api/dictionaries/status", None),
    ("GET", "/api/dictionaries/log", None),
    ("GET", "/api/dictionaries/sources", None),
    ("GET", "/api/dictionaries/regions", None),
    ("GET", "/api/dictionaries/region-links", None),
    ("GET", "/api/dictionaries/region-links?includeUnavailable=true", None),
    ("GET", "/api/dictionaries/region-links/suggest", None),
    ("GET", "/api/dictionaries/entries?kind=spdept&search=ТУ", None),
    ("GET", "/api/dict", None),
    ("GET", "/api/dict/spdept", None),
    ("GET", "/api/prk/history?limit=1", None),
    ("GET", "/api/prk/stats", None),
    ("POST", "/api/mis/search-patients", {
        "params": {
            "PersonSurName_SurName": "ТЕСТ",
            "searchMode": "all",
            "page": 1,
            "start": 0,
            "limit": 1,
        },
    }),
    ("POST", "/api/mis/get-regions-id", {
        "params": {"Lpu_id": "13003795", "object": "LpuRegion", "isClose": "1"},
    }),
    ("PUT", "/api/v1/auth/mis-credentials", {"login": "", "password": ""}),
    ("PUT", "/api/v1/auth/mis-config", {"baseUrl": ""}),
    ("PUT", "/api/v1/auth/mis-config", {"baseUrl": "ftp://wrong"}),
    ("POST", "/api/dictionaries/region-links", {"podr": ""}),
    ("POST", "/api/dictionaries/region-links/forget", {"podr": "999999"}),
    ("POST", "/api/dictionaries/region-links/apply", {"links": []}),
    ("POST", "/api/dictionaries/load", {"kind": "nonsense"}),
    ("GET", "/api/dictionaries/entries?kind=nonsense", None),
]

EXPECTED_CLIENT_ERRORS = {
    ("PUT", "/api/v1/auth/mis-credentials"),
    ("PUT", "/api/v1/auth/mis-config"),
    ("POST", "/api/dictionaries/load"),
}


def main() -> int:
    failures = []
    print(f"Smoke test → {BASE}\n")

    # POST /api/settings проверяем, записав текущие значения без изменений.
    try:
        current = read_settings()
    except Exception as e:
        print(f"  [FAIL] не удалось прочитать настройки: {e}")
        return 1
    roundtrip = {k: current.get(k, "") for k in
                 ("user", "password", "defaultMo", "misLpuId", "misLogin", "misPassword")}
    checks = [("POST", "/api/settings", roundtrip)] + STATIC_CHECKS

    for method, path, body in checks:
        status, snippet = call(method, path, body)
        if (method, path) in EXPECTED_CLIENT_ERRORS:
            mark = "ok" if 400 <= status < 500 else "FAIL"
        else:
            mark = "FAIL" if status >= 500 or status == 0 else "ok"
        print(f"  [{mark:>4}] {method:<5} {path:<48} {status}")
        if mark == "FAIL":
            failures.append((method, path, status, snippet))

    # Настройки не должны были измениться.
    try:
        after = read_settings()
        for key in roundtrip:
            if after.get(key) != roundtrip[key]:
                failures.append(("VERIFY", f"settings.{key}", 0,
                                 f"{roundtrip[key]!r} -> {after.get(key)!r}"))
                print(f"  [FAIL] settings.{key} изменился: "
                      f"{roundtrip[key]!r} -> {after.get(key)!r}")

        # Пустые адреса и пустой Lpu_id — тихий отказ: система запустится, но
        # SOAP-обмен и сохранение в ЕЦП работать не будут.
        for key, label in (("iasUrl", "адрес ИАС (прикрепление)"),
                           ("iasCheckUrl", "адрес ИАС (проверка полиса)"),
                           ("ecpUrl", "адрес ЕЦП"),
                           ("misLpuId", "ID МО для ЕЦП")):
            if not (after.get(key) or "").strip():
                failures.append(("VERIFY", f"settings.{key} пусто", 0, f"не задан {label}"))
                print(f"  [FAIL] settings.{key} пусто — не задан {label}. "
                      f"Проверьте переменные SOAP_URL / SOAP_CHECK_URL / MIS_BASE_URL в .env.")
    except Exception as e:
        failures.append(("VERIFY", "settings", 0, str(e)))

    if failures:
        print("\nПровалено:")
        for method, path, status, snippet in failures:
            print(f"  {method} {path} -> {status}\n    {snippet}")
        return 1
    print("\nВсе маршруты отвечают без 5xx, настройки не изменены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())