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

from app.services import dict_db, region_match

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

    region, how = region_match.match_region(regions, code)
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


def mo_entries(mo: str = "") -> list[dict]:
    """Подразделения ИАС-4 того МО, который задан в настройках.

    Сопоставлять нужно только свои подразделения: в выгрузке 159 медицинских
    организаций, и чужие коды в таблице сопоставления только мешают.
    """
    code = (mo or "").strip().lstrip("0")
    rows = dict_db.get_entries("spdept", code)
    if rows:
        return rows
    return dict_db.get_entries("spdept")


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
            guess, guess_how = region_match.match_region(regions, code)
            how = f"не привязано, автоподбор: {guess_how}" if guess else "не привязано"

        rows.append({
            "podr": code,
            "name": entry.get("name") or "",
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
            guess, _ = region_match.match_region(regions, row["podr"])
            if guess:
                auto[region_match.region_id(guess)] = row["podr"]
    for item in free:
        item["linkedBy"] = auto.get(item["regionId"], "")

    manual = sum(1 for r in rows if r["source"] == "manual")
    unlinked = sum(1 for r in rows if r["source"] == "unlinked")
    linked_expired = sum(1 for r in rows if r["linked"] and not r["actual"])
    return {
        "lpuId": lpu_id,
        "rows": rows,
        "freeRegions": free,
        "summary": {
            "ias": len(rows),
            "linked": sum(1 for r in rows if r["linked"]),
            "manual": manual,
            "unlinked": unlinked,
            "unresolved": sum(1 for r in rows if not r["linked"] and not r["source"]),
            "broken": sum(1 for r in rows if r["how"] == HOW_MISSING_REGION),
            "regions": len(regions),
            "regionsUsed": len(used),
            "regionsFree": len(free),
            "expired": sum(1 for r in rows if not r["actual"]),
            "linkedExpired": linked_expired,
        },
    }


def suggest(lpu_id: str, regions: list[dict], ias: list[dict]) -> list[dict]:
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
        region, how = region_match.match_region(regions, code)
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