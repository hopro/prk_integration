"""Сопоставление подразделения ИАС-4 с участком ЕЦП.

ИАС-4 присылает код подразделения (`podr`), а ЕЦП хранит участки под именами
(`LpuRegion_Name`). Имена у ЕЦП бывают разной формы:

    21100                      — просто код
    31400_ГП3                  — код с суффиксом подразделения
    ОВП п. Первомайский        — текст без кода
    ОВП п. Первомайский 233100_ГРП  — текст с кодом и суффиксом

Поэтому сравнение идёт по нормализованному виду: суффикс `_ГП3`/`_ГРП` и хвостовой
код отбрасываются, регистр и пробелы не учитываются.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Хвостовой суффикс вида _ГП3, _ГРП, _ДПО и т.п.
_SUFFIX_RE = re.compile(r"_[А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z0-9]*$")
# Хвостовой код: «233100_ГРП», « 233100 », «9002»
_TAIL_CODE_RE = re.compile(r"[\s_]*\d[\d_]*[А-ЯЁA-Zа-яёa-z]*\s*$")
# Хвостовые цифры — собственно код участка.
_TAIL_DIGITS_RE = re.compile(r"(\d+)\s*$")


def normalize(value: str) -> str:
    """Приводит значение к сравнимому виду.

    «ОВП п. Первомайский 233100_ГРП» → «овп п. первомайский»
    «31400_ГП3»                        → «31400»
    « 21100 »                         → «21100»
    """
    text = (value or "").strip()
    if not text:
        return ""

    def drop_suffix(candidate: str) -> str:
        return _SUFFIX_RE.sub("", candidate).strip() or candidate

    text = drop_suffix(text)
    # Хвостовой код снимаем, только если после этого что-то остаётся: иначе
    # строка сама является кодом («21100», «9002») и снять её нельзя.
    candidate = drop_suffix(_TAIL_CODE_RE.sub("", text).strip())
    if candidate:
        text = candidate
    return re.sub(r"\s+", " ", text).lower()


def region_value(region: dict) -> str:
    """Название участка из строки кэша или из ответа ЕЦП."""
    return (region.get("name") or region.get("LpuRegion_Name") or "").strip()


def region_id(region: dict) -> str:
    return str(region.get("region_id") or region.get("LpuRegion_id") or "").strip()


def region_descr(region: dict) -> str:
    """Описание участка из ЕЦП (`LpuRegion_Descr`).

    Часто полезнее имени: участок с именем «20100» описывается как
    «Терапевтический участок 1», и по описанию он находится в справочнике
    подразделений ИАС-4, где подразделение названо словами, а не кодом.
    """
    return (region.get("descr") or region.get("LpuRegion_Descr") or "").strip()


def region_code(value: str) -> str | None:
    """Код участка, который ИАС-4 присылает в поле podr.

    ИАС оперирует короткими кодами (`20100`, `31400`), а ЕЦП хранит участок под
    именем, которое может быть длиннее и с суффиксом: `30100_ГП3`,
    `523102_ГРП`, `ОВП № 1 п.Новоасбест`. Из названий без числа кода не
    извлечь, и такие участки в списке выбора не показываются: ИАС такой код
    всё равно не пришлёт.

    Возвращает None, если кода в имени нет.
    """
    text = (value or "").strip()
    if not text:
        return None

    # Сначала убираем суффикс подразделения (_ГП3, _ГРП), затем берём хвостовые
    # цифры. Такой порядок важен: по одному регулярному выражению «30100_ГП3»
    # распадался на «3».
    without_suffix = _SUFFIX_RE.sub("", text).strip() or text
    tail = _TAIL_DIGITS_RE.search(without_suffix)
    return tail.group(1) if tail else None


def match_region(regions: list[dict], podr: str) -> tuple[dict | None, str]:
    """Ищет участок по коду подразделения.

    Возвращает (участок, способ сопоставления). Способ нужен для диагностики:
    по нему видно, почему участок не нашёлся или почему найден «похожий».
    """
    target = (podr or "").strip()
    if not target or not regions:
        return None, "нет данных"

    # 1. Точное совпадение как есть — самый частый случай.
    for region in regions:
        if region_value(region) == target:
            return region, "точное"

    # 2. Нормализованное совпадение (падеж регистра, суффикс _ГП3, хвостовой код).
    wanted = normalize(target)
    if wanted:
        for region in regions:
            if normalize(region_value(region)) == wanted:
                return region, "нормализованное"

    # 3. Подразделение ИАС могло прийти с префиксом МО: 700200 → 200.
    digits = re.findall(r"\d+", target)
    for value in digits:
        tail = value.lstrip("0")
        if tail and len(tail) < len(value):
            for region in regions:
                if normalize(region_value(region)) == tail:
                    return region, "хвост кода без ведущих нулей"

    # 4. То же самое по описанию участка: имя в ЕЦП бывает кодом, а смысл
    #    подразделения живёт в описании.
    wanted_descr = normalize(target)
    for region in regions:
        if region_descr(region) == target:
            return region, "описание участка"
    for region in regions:
        value = normalize(region_descr(region))
        if value and value == wanted_descr:
            return region, "нормализованное описание участка"

    # 5. Совпадение по вхождению — только для текстовых названий. Для чистых
    #    кодов это даёт ложные срабатывания: «530200» входит в «30200».
    is_code = wanted.isdigit()
    if wanted and not is_code:
        for region in regions:
            value = normalize(region_value(region))
            if value and (value in wanted or wanted in value):
                logger.info("Region %s matched by containment", region_value(region))
                return region, "вхождение"
        for region in regions:
            value = normalize(region_descr(region))
            if value and (value in wanted or wanted in value):
                logger.info("Region %s matched by descr containment", region_value(region))
                return region, "вхождение в описании"

    return None, "не найдено"


def diagnose(regions: list[dict], podr: str, lpu_id: str) -> str:
    """Человекочитаемое объяснение, почему участок не нашёл."""
    target = (podr or "").strip()
    total = len(regions)
    if not target:
        return "ИАС-4 не вернул код подразделения (podr)."
    if total == 0:
        return (
            f"Справочник участков ЛПУ {lpu_id} пуст — загрузите его на вкладке «Справочники» "
            "(кнопка «Загрузить»)."
        )

    wanted = normalize(target)
    close = []
    if wanted:
        for region in regions:
            for value in (region_value(region), region_descr(region)):
                value = normalize(value)
                if value and (value in wanted or wanted in value):
                    label = region_value(region)
                    descr = region_descr(region)
                    text = f"{label} ({descr})" if descr and descr != label else label
                    if text not in close:
                        close.append(text)

    hint = (
        f"Ближайшие по названию: {', '.join(close[:5])}."
        if close else
        f"Ни одного участка, похожего на «{target}». Посмотрите, как этот код "
        "назван в справочнике ИАС-4, и привяжите его на странице «Сопоставление участков»."
    )
    return (
        f"Подразделение «{target}» отсутствует среди {total} участков ЛПУ {lpu_id}. {hint}"
    )