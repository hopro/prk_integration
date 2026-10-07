"""Сопоставление подразделения ИАС-4 с участком ЕЦП.

Два справочника используют разные нумерации:

* ИАС-4 принимает в поле `podr` короткий код подразделения из справочника
  подразделений ИАС-4;
* ЕЦП хранит участок под именем `LpuRegion_Name`, где код может быть
  другим, а может отсутствовать вовсе.

Автоматически совпадают единицы из десятков: у ГП № 4 (МО 893, ЛПУ 13003795)
из 107 участков ЕЦП ни один код с суффиксом `_ГРП` не встречается в
справочнике ИАС-4. Поэтому основной способ — ручная привязка на странице
«Сопоставление участков».

Порядок выбора:

1. ручная привязка администратора;
2. осознанный отказ от привязки — участок не подставляется вовсе;
3. автоматический подбор по названию;
4. не найдено.
"""

import datetime
import logging

from app.services import dict_db, region_match, settings_db

logger = logging.getLogger(__name__)

# Человеческие названия способов сопоставления: они показываются в интерфейсе
# и в истории прикреплений, поэтому формулировки должны быть понятны админу.
HOW_MANUAL = "вручную"
HOW_AUTO = "автоматически"
HOW_UNLINKED = "отвязано вручную"
HOW_MISSING_REGION = "участок не найден в ЕЦП"
HOW_NOT_FOUND = "не найдено"


def _regions_by_id(regions: list[dict]) -> dict[str, dict]:
    return {region_match.region_id(r): r for r in regions if region_match.region_id(r)}


def resolve(
    lpu_id: str,
    podr: str,
    regions: list[dict],
    links: dict[str, dict] | None = None,
    dept_name: str = "",
) -> tuple[dict | None, str]:
    """Возвращает участок ЕЦП для кода подразделения и способ сопоставления.

    links можно передать заранее, когда он уже прочитан: при отправке
    прикрепления это снимает лишний запрос к базе на каждое подразделение.
    """
    code = (podr or "").strip()
    if not code:
        return None, "нет кода"

    links = dict_db.get_region_links(lpu_id) if links is None else links
    link = links.get(code)

    if link is not None:
        if not (link.get("region_id") or "").strip():
            # Администратор решил, что этому подразделению участок не нужен.
            # Автоподбор здесь не применяем: он и был причиной ошибки.
            return None, HOW_UNLINKED
        region = _regions_by_id(regions).get(link["region_id"])
        if region is not None:
            return region, HOW_MANUAL if (link.get("source") == "manual") else HOW_AUTO
        # Участок исчез из ЕЦП после привязки. Не подставляем наугад: код уйдёт
        # в ЕЦП с чужим LpuRegion_id.
        logger.warning(
            "Region link lpu=%s podr=%s points to missing region_id=%s",
            lpu_id, code, link.get("region_id"),
        )
        return None, "привязанный участок не найден в ЕЦП"

    region, how = region_match.match_region(regions, code, dept_name)
    if region is None:
        return None, HOW_NOT_FOUND
    return region, f"автоматически ({how})"


def diagnose(
    lpu_id: str,
    podr: str,
    regions: list[dict],
    links: dict[str, dict] | None = None,
    ias_names: dict[str, str] | None = None,
) -> str:
    """Объяснение для администратора, почему участок не нашёлся."""
    code = (podr or "").strip()
    links = dict_db.get_region_links(lpu_id) if links is None else links
    link = links.get(code)

    if link is not None and not (link.get("region_id") or "").strip():
        return (
            f"Подразделение {code} отвязано вручную на странице «Сопоставление участков». "
            "Привяжите его к участку ЕЦП или верните автоматический подбор."
        )
    if link is not None and link["region_id"] not in _regions_by_id(regions):
        return (
            f"Подразделение {code} привязано к участку ЕЦП {link['region_id']}, "
            "но этого участка больше нет в списке. Обновите участки из ЕЦП "
            "или привяжите подразделение заново."
        )

    name = (ias_names or {}).get(code)
    title = f"Подразделение {code}" + (f" «{name}»" if name else "")
    base = region_match.diagnose(regions, code, lpu_id)
    if not regions:
        return base
    return (
        f"{title} не привязано к участку ЕЦП. {base} "
        "Привяжите вручную на странице «Сопоставление участков»."
    )


# Подразделения и ФАПы живут в двух выгрузках с разным написанием кода МО:
# для ГП № 4 в SPDEPT это «893», а в SPSUBDEPT — «660893». Коды подразделений
# при этом не пересекаются, поэтому таблица связей остаётся одна.
IAS_DEPT_KINDS = ("spdept", "spsubdept")


def _mo_code(mo: str = "") -> str:
    """Код медицинской организации: из запроса, иначе из настроек."""
    return (mo or "").strip().lstrip("0") or (
        settings_db.get_settings().get("defaultMo") or ""
    ).strip().lstrip("0")


def _mo_scope(kind: str, mo: str) -> str:
    """Код МО в справочнике вида `kind`.

    Для подразделений ищем точное совпадение, для ФАПов — по окончанию кода:
    в SPSUBDEPT код записан длиннее на 3 цифры региона. Окончание ищется при
    коде от трёх цифр и только если совпадение единственное, иначе подразделения
    чужих организаций попали бы в список.
    """
    code = _mo_code(mo)
    if not code:
        return ""
    scopes = [r["scope"] for r in dict_db.entry_scopes(kind) if r["scope"]]
    if code in scopes:
        return code
    if kind == "spsubdept" and len(code) >= 3:
        matches = [s for s in scopes if s.endswith(code)]
        if len(matches) == 1:
            return matches[0]
    return ""


def mo_entries(mo: str = "", include_unavailable: bool = False) -> list[dict]:
    """Подразделения и ФАПы того МО, который задан в настройках.

    По умолчанию возвращается только то, к чему ИАС-4 примет прикрепление:
    действующие подразделения с признаком «разрешено прикрепление». Закрытые по
    сроку действия он отклоняет с 501, а снятые с признака — с 502, поэтому в
    сопоставлении им не место.

    include_unavailable=True возвращает всё, включая закрытые и запрещённые, —
    это нужно для галочки в интерфейсе.
    """
    today = datetime.date.today().isoformat()
    result: list[dict] = []
    for kind in IAS_DEPT_KINDS:
        scope = _mo_scope(kind, mo)
        for row in dict_db.get_entries(kind, scope):
            if not include_unavailable:
                valid_until = row.get("valid_until") or ""
                if valid_until not in ("", "9999-12-31") and valid_until < today:
                    continue
                if (row.get("can_attach") or "") == "0":
                    continue
            row["kind"] = kind
            result.append(row)
    return result


# Подпись источника подразделения: обычное подразделение или ФАП.
KIND_LABELS = {"spdept": "подразделение", "spsubdept": "ФАП"}


def picker_entries(mo: str = "") -> tuple[list[dict], dict]:
    """Подразделения для формы прикрепления: действующие и пригодные.

    ИАС-4 принимает в поле podr коды из обоих справочников, поэтому ФАПы стоят
    рядом с обычными подразделениями и различаются пометкой источника.
    Закрытые (DEND в прошлом) и запрещённые (PRKYES=0) отсекаются: ИАС-4
    отклонит их с кодом 501 или 502.

    Возвращает записи и сводку: всего в справочниках МО, сколько пригодно.
    """
    today = datetime.date.today().isoformat()
    mo_code = _mo_code(mo)
    result: list[dict] = []
    total = 0
    for kind in IAS_DEPT_KINDS:
        scope = _mo_scope(kind, mo)
        rows = dict_db.get_entries(kind, scope)
        total += len(rows)
        for row in rows:
            valid_until = row.get("valid_until") or ""
            if valid_until not in ("", "9999-12-31") and valid_until < today:
                continue
            if (row.get("can_attach") or "") == "0":
                continue
            result.append({**row, "kind": kind, "source": KIND_LABELS.get(kind, kind)})
    result.sort(key=lambda r: r["name"])
    return result, {"total": total, "actual": len(result), "mo": mo_code}


def dept_name(podr: str, mo: str = "") -> str:
    """Название подразделения ИАС-4 по его коду.

    Нужно при отправке прикрепления: без привязки участок ищется по коду и по
    названию, а у ФАПов код в ЕЦП не встречается.
    """
    code = (podr or "").strip()
    if not code:
        return ""
    for kind in IAS_DEPT_KINDS:
        scope = _mo_scope(kind, mo)
        for row in dict_db.get_entries(kind, scope, search=code):
            if (row.get("code") or "").strip() == code:
                return row.get("name") or ""
    return ""


def build_matrix(
    lpu_id: str,
    regions: list[dict],
    ias: list[dict],
    links: dict[str, dict] | None = None,
) -> dict:
    """Таблица сопоставления для страницы администратора.

    По каждому коду подразделения ИАС-4 показывает, какой участок ЕЦП к нему
    привязан и каким способом. Участки, к которым ничего не привязано,
    собираются отдельно — их можно занять вручную.
    """
    links = dict_db.get_region_links(lpu_id) if links is None else links
    by_id = _regions_by_id(regions)

    rows = []
    used: set[str] = set()
    today = datetime.date.today().isoformat()
    for entry in ias:
        code = str(entry.get("code") or "").strip()
        if not code:
            continue
        # Закрытые подразделения показываем, но помечаем: ИАС-4 их не примет,
        # и привязка к ним скорее всего сделана ошибочно.
        valid_until = entry.get("valid_until") or ""
        actual = valid_until in ("", "9999-12-31") or valid_until >= today
        link = links.get(code)
        region_id = (link or {}).get("region_id") or ""
        region = by_id.get(region_id)
        source = (link or {}).get("source") or ""
        if region is not None:
            used.add(region_id)
            # Способ различаем по записи о привязке: «auto» означает, что
            # участок подобрался автоматически и администратор его принял,
            # а не то, что привязка снята.
            how = {
                "manual": HOW_MANUAL,
                "auto": HOW_AUTO,
                "unlinked": HOW_UNLINKED,
            }.get(source, HOW_AUTO)
        elif region_id:
            how = HOW_MISSING_REGION
        elif link is not None:
            how = HOW_UNLINKED
        else:
            # Привязки нет — показываем, что предложил бы автоподбор, но не
            # записываем это в базу: решение остаётся за администратором.
            guess, guess_how = region_match.match_region(
                regions, code, entry.get("name") or ""
            )
            how = f"не привязано, автоподбор: {guess_how}" if guess else "не привязано"

        rows.append({
            "podr": code,
            "name": entry.get("name") or "",
            # Подразделение или ФАП — приходят из разных выгрузок. Ключ origin,
            # потому что source ниже занят видом привязки: manual/auto/unlinked.
            "origin": KIND_LABELS.get(entry.get("kind", ""), entry.get("source") or ""),
            "address": entry.get("address") or "",
            "canAttach": (entry.get("can_attach") or "") != "0",
            "regionId": region_id,
            "regionName": region_match.region_value(region) if region else (link or {}).get("region_name", ""),
            "regionDescr": region_match.region_descr(region) if region else "",
            "source": (link or {}).get("source") or "",
            "updatedAt": (link or {}).get("updated_at") or "",
            "how": how,
            "linked": region is not None,
            "actual": actual,
            "validUntil": valid_until if valid_until != "9999-12-31" else "",
        })

    rows.sort(key=lambda r: (not r["actual"], r["linked"], r["podr"]))
    free = [
        {
            "regionId": region_match.region_id(r),
            "name": region_match.region_value(r),
            "descr": region_match.region_descr(r),
            "linkedBy": "",
        }
        for r in regions
        if region_match.region_id(r) and region_match.region_id(r) not in used
    ]
    # Подсказываем, какой код подразделения претендует на свободный участок:
    # так администратору не приходится искать соответствие в уме.
    auto = {}
    for row in rows:
        if not row["linked"] and not row["regionId"]:
            guess, _ = region_match.match_region(regions, row["podr"], row["name"])
            if guess:
                auto[region_match.region_id(guess)] = row["podr"]
    for item in free:
        item["linkedBy"] = auto.get(item["regionId"], "")

    manual = sum(1 for r in rows if r["source"] == "manual")
    return {
        "lpuId": lpu_id,
        "rows": rows,
        "freeRegions": free,
        "summary": {
            "ias": len(rows),
            "linked": sum(1 for r in rows if r["linked"]),
            "manual": manual,
            "unresolved": sum(1 for r in rows if not r["linked"] and not r["source"]),
            "regions": len(regions),
            "regionsUsed": len(used),
            "regionsFree": len(free),
            "faps": sum(1 for r in rows if r["origin"] == KIND_LABELS["spsubdept"]),
        },
    }


def suggest(lpu_id: str, regions: list[dict], ias: list[dict]) -> list[dict]:
    """Что предложил бы автоматический подбор. Ничего не сохраняет.

    Закрытые подразделения и подразделения без признака «разрешено
    прикрепление» не предлагаются: ИАС-4 их отклонит с 501 и 502.
    """
    """Автоподбор для кодов без ручной привязки.

    Участок не предлагается, если он уже занят другим подразделением: иначе
    один участок ЕЦП навязался бы двум кодам, и прикрепление стало бы
    неоднозначным.
    """
    links = dict_db.get_region_links(lpu_id)
    taken = {(l.get("region_id") or "").strip() for l in links.values() if l.get("region_id")}

    today = datetime.date.today().isoformat()
    result = []
    for entry in ias:
        code = str(entry.get("code") or "").strip()
        if not code or code in links:
            continue
        valid_until = entry.get("valid_until") or ""
        if valid_until not in ("", "9999-12-31") and valid_until < today:
            continue  # закрытое подразделение предлагать незачем
        if (entry.get("can_attach") or "") == "0":
            continue  # ИАС-4 отклонит такое прикрепление с кодом 502
        region, how = region_match.match_region(
            regions, code, entry.get("name") or ""
        )
        if region is None:
            continue
        region_id = region_match.region_id(region)
        if region_id in taken:
            continue
        taken.add(region_id)
        result.append({
            "podr": code,
            "name": entry.get("name") or "",
            "region_id": region_id,
            "region_name": region_match.region_value(region),
            "how": how,
            "source": "auto",
        })
    return result