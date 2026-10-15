"""
sheet_reader.py
===============

Чтение реальных месячных вкладок расписания занятости компьютерных классов.

Фактическая раскладка вкладки (снята дампом probe.py):

    строка 1 : A="Дата"  B="Д/н"  C..= номера кабинетов (каждый объединён на 2 колонки)
    строка 2 : под каждым кабинетом две подколонки: "Утро 9.30-14.40", "Вечер 15-19.50"
    строки 3+: A="12-янв." (или "28"), B="пн", далее ячейки занятости
    ниже     : пустая строка, затем строка-инструкция (её игнорируем)

Ячейка слота либо пуста (класс свободен), либо содержит занятие вида:
    "9.2.ОЦ.6.1 (Веснинова Е.Н.)"
    "9.30-12.40 4.2.ОЦ.2.2 (Кузина Н.Н.)"
    "16.00 ГМО Бакшинова Л.П. (Евтух Е.В.)"
    "Логопедия (Евтух Е.В.)"
    "ESTEL"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from google_sheets_client import GoogleSheetsClient, col_number_to_letter

# ------------------------------------------------------------------ словарь
MONTH_NAMES: dict[str, int] = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}
# сокращения из колонки "Дата": "12-янв.", "2-февр.", "30-мар.", "2-нояб."
MONTH_ABBR: dict[str, int] = {
    "янв": 1, "февр": 2, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5,
    "июн": 6, "июл": 7, "авг": 8, "сент": 9, "сен": 9, "окт": 10, "нояб": 11,
    "ноя": 11, "дек": 12,
}
WEEKDAY_RU = {"пн": "пн", "вт": "вт", "ср": "ср", "чт": "чт", "пт": "пт",
              "сб": "сб", "вс": "вс"}

MORNING = "Утро (9.30–14.40)"
EVENING = "Вечер (15.00–19.50)"
SHIFTS = (MORNING, EVENING)

FIRST_DATA_COL = 3  # колонка C
ROW_ROOM_HEADER = 1
ROW_SHIFT_HEADER = 2
ROW_FIRST_DAY = 3

# строки, которые начинаются как примечание, а не как дата
NOTE_PREFIXES = ("в ячейках", "примечание", "подсказка", "декабрь")

# Время в начале ячейки: либо диапазон ("9.30-12.40", "9.30 до 12.00",
# "14.00 -15.00"), либо одиночная отметка ("16.00", "10.30").
# Одиночная отметка засчитывается только если дальше идёт пробел/конец, а не
# точка: иначе "16.10.ОЦ.1" — это идентификатор группы, а не 16:10.
_RE_TIME_RANGE = re.compile(
    r"^\s*\+?\(?\s*(\d{1,2}[.:]\d{2})\s*(?:-|—|–|до)\s*(\d{1,2}[.:]\d{2})\s*\)?\s+",
)
_RE_TIME_SINGLE = re.compile(
    r"^\s*\+?\(?\s*(\d{1,2}[.:]\d{2})\s*\)?(?=[\s,;)]|$)",
)
_RE_PARENS = re.compile(r"[(（]\s*(.+?)\s*[)）]\s*$")
_RE_TRAILING_PARENS = re.compile(r"[(（][^()]*[)）]")


# ------------------------------------------------------------------- модели
@dataclass
class Slot:
    """Одна ячейка сетки: кабинет + дата + смена."""
    room: str
    day: date
    shift: str
    raw: str
    course: str
    person: str
    time_note: str
    uncertain: bool
    weekday_label: str = ""
    simulated: bool = False

    @property
    def occupied(self) -> bool:
        return bool(self.raw)

    @property
    def weekday(self) -> str:
        """Метка дня недели: из колонки B, при её отсутствии — из даты."""
        if self.weekday_label:
            return self.weekday_label
        return _WEEKDAY_ABBR[self.day.weekday()]


_WEEKDAY_ABBR = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass
class MonthGrid:
    """Разобранная месячная вкладка."""
    title: str
    year: int
    month: int
    rooms: list[str]
    slots: list[Slot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        names = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май",
                 6: "июнь", 7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь",
                 11: "ноябрь", 12: "декабрь"}
        return f"{names[self.month]} {self.year}"

    @property
    def days(self) -> list[date]:
        seen = sorted({s.day for s in self.slots})
        return seen

    @property
    def scheduled(self) -> list[Slot]:
        return [s for s in self.slots if s.occupied]


@dataclass
class MonthRef:
    """Месяц, доступный в таблице, для выбора в интерфейсе."""
    title: str
    year: int
    month: int

    @property
    def label(self) -> str:
        names = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май",
                 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь",
                 11: "Ноябрь", 12: "Декабрь"}
        return f"{names[self.month]} {self.year}"


# --------------------------------------------------------------- заголовки
def parse_month_title(title: str) -> tuple[int, int] | None:
    """'Октябрь 2026  ' -> (2026, 10). None, если вкладка не месячная."""
    text = " ".join(title.split()).lower()
    match = re.match(r"^([а-яё]+)\s+(\d{4})$", text)
    if not match:
        return None
    month = MONTH_NAMES.get(match.group(1))
    if not month:
        return None
    return int(match.group(2)), month


def list_months(client: GoogleSheetsClient) -> list[MonthRef]:
    """Все месячные вкладки таблицы, отсортированные по дате."""
    refs: list[MonthRef] = []
    for title in client.sheet_titles():
        parsed = parse_month_title(title)
        if parsed:
            refs.append(MonthRef(title=title, year=parsed[0], month=parsed[1]))
    return sorted(refs, key=lambda r: (r.year, r.month))


# ------------------------------------------------------------ разбор ячейки
def parse_cell(raw: Any) -> tuple[str, str, str, bool]:
    """'9.30-12.40 4.2.ОЦ.2.2 (Кузина Н.Н.)' -> (course, person, time, uncertain)."""
    text = " ".join(str(raw).split()).strip() if raw is not None else ""
    if not text:
        return "", "", "", False

    uncertain = text.startswith("?")
    text = text.lstrip("?* ").strip()

    time_note = ""
    consumed = 0
    if (rng := _RE_TIME_RANGE.match(text)):
        time_note = f"{rng.group(1)}–{rng.group(2)}"
        consumed = rng.end()
    elif (single := _RE_TIME_SINGLE.match(text)):
        time_note = single.group(1)
        consumed = single.end()
    if consumed:
        text = text[consumed:].strip()

    person = ""
    inner = _RE_PARENS.search(text)
    if inner:
        person = inner.group(1).strip(" .,;")
        text = text[:inner.start()].strip(" -–—,.")

    course = text.strip(" -–—,.;")
    return course, person, time_note, uncertain


# ------------------------------------------------------------- чтение вкладки
def _room_columns(client: GoogleSheetsClient, title: str,
                  header: list[Any]) -> list[tuple[str, int, int]]:
    """[(кабинет, первая колонка, последняя колонка)], span берётся из слияний."""
    spans: dict[int, int] = {}
    try:
        meta = client._execute(  # noqa: SLF001
            client.service.spreadsheets().get(
                spreadsheetId=client.spreadsheet_id,
                ranges=[f"'{title}'!A1:BZ2"],
                fields="sheets.merges",
            )
        )
        for merge in meta["sheets"][0].get("merges", []):
            if merge.get("startRowIndex") == ROW_ROOM_HEADER - 1:
                spans[merge["startColumnIndex"]] = (
                    merge["endColumnIndex"] - merge["startColumnIndex"])
    except Exception:  # noqa: BLE001 - слияния лишь уточняют ширину
        pass

    rooms: list[tuple[str, int, int]] = []
    col = FIRST_DATA_COL
    while col <= len(header):
        value = header[col - 1]
        if value is not None and str(value).strip():
            span = spans.get(col - 1, 2)
            span = max(1, min(span, 6))
            rooms.append((" ".join(str(value).split()), col, col + span - 1))
            col += span
        else:
            col += 1
    return rooms


def _parse_day_cell(value: Any, year: int, month: int) -> date | None:
    """'12-янв.' / '28' / '30-мар.' -> date."""
    text = str(value).strip().lower().rstrip(".") if value is not None else ""
    if not text or text.startswith(NOTE_PREFIXES):
        return None
    match = re.match(r"^(\d{1,2})\s*[-.]?\s*([а-яё]{2,6})?", text)
    if not match:
        return None
    day = int(match.group(1))
    if not 1 <= day <= 31:
        return None
    resolved = month
    if match.group(2):
        abbr = match.group(2).rstrip(".")
        resolved = MONTH_ABBR.get(abbr, month)
    try:
        return date(year, resolved, day)
    except ValueError:
        return None


def read_month(client: GoogleSheetsClient, ref: MonthRef,
               max_rows: int = 80) -> MonthGrid:
    """Читает и нормализует одну месячную вкладку."""
    rows_needed = min(max_rows, client.grid_size(ref.title)[0])
    raw = client.read(f"A1:AZ{rows_needed}", sheet=ref.title)
    grid = MonthGrid(title=ref.title, year=ref.year, month=ref.month, rooms=[])

    if len(raw) < ROW_FIRST_DAY:
        grid.warnings.append("вкладка слишком короткая — шапка расписания не найдена")
        return grid

    header = raw[ROW_ROOM_HEADER - 1]
    shift_row = raw[ROW_SHIFT_HEADER - 1]
    rooms = _room_columns(client, ref.title, header)
    if not rooms:
        grid.warnings.append("не найдены номера кабинетов в строке 1")
        return grid

    # подпись смены важнее позиции: ищем "утро"/"вечер" в подколонках
    resolved: list[tuple[str, int, int, str]] = []
    for room, c1, c2 in rooms:
        for col in range(c1, c2 + 1):
            label = str(shift_row[col - 1]).lower() if col - 1 < len(shift_row) else ""
            if "утр" in label:
                shift = MORNING
            elif "веч" in label:
                shift = EVENING
            else:
                shift = MORNING if col == c1 else EVENING
            resolved.append((room, col, col, shift))
    grid.rooms = list(dict.fromkeys(room for room, *_ in resolved))

    # строки дней: идём, пока колонка A похожа на дату
    for index in range(ROW_FIRST_DAY - 1, len(raw)):
        row = raw[index]
        if not row or all(c is None or not str(c).strip() for c in row):
            if index > ROW_FIRST_DAY - 1 and grid.slots:
                break                      # пустая строка = конец таблицы расписания
            continue
        day = _parse_day_cell(row[0], ref.year, ref.month)
        if day is None:
            if grid.slots:
                break                      # строка-примечание после данных
            continue
        if day.month != ref.month:
            continue                       # заметка о другом месяце
        label = str(row[1]).strip().lower() if len(row) > 1 and row[1] else ""
        weekday_label = label if label in WEEKDAY_RU else ""
        for room, col, _last, shift in resolved:
            value = row[col - 1] if col - 1 < len(row) else None
            raw_text = " ".join(str(value).split()) if value is not None else ""
            # значение может стоять во второй колонке объединённой ячейки
            if not raw_text and col + 1 <= _last:
                for extra in range(col + 1, _last + 1):
                    if extra - 1 < len(row) and row[extra - 1]:
                        raw_text = " ".join(str(row[extra - 1]).split())
                        break
            course, person, time_note, uncertain = parse_cell(raw_text)
            grid.slots.append(Slot(
                room=room, day=day, shift=shift, raw=raw_text,
                course=course, person=person, time_note=time_note,
                uncertain=uncertain, weekday_label=weekday_label,
            ))
    if not grid.slots:
        grid.warnings.append("не найдено ни одного дня в колонке A")
    return grid


def read_months(client: GoogleSheetsClient, refs: list[MonthRef],
                on_progress: Any = None) -> list[MonthGrid]:
    grids: list[MonthGrid] = []
    for ref in refs:
        if on_progress:
            on_progress(f"Читаю вкладку «{ref.title.strip()}»…")
        grids.append(read_month(client, ref))
    return grids


# ------------------------------------------------------------- фильтрация
@dataclass
class Filters:
    rooms: tuple[str, ...] = ()
    courses: tuple[str, ...] = ()
    persons: tuple[str, ...] = ()
    shifts: tuple[str, ...] = ()
    weekdays: tuple[str, ...] = ()


def parallel_of(course: str) -> str:
    """'9.2.ОЦ.6.1' -> '9'; курсы без нумерации -> 'курсы'.

    Используется только как необязательная группировка: идентификаторы вида
    '16.10.ОЦ.3' — это коды мероприятий, а не классы, поэтому параллель не
    является надёжным признаком и в отчёте не фигурирует.
    """
    match = re.match(r"^(\d{1,2})\b", course.strip())
    return match.group(1) if match else "курсы"


def apply_filters(slots: Iterable[Slot], f: Filters) -> list[Slot]:
    out: list[Slot] = []
    for s in slots:
        if f.rooms and s.room not in f.rooms:
            continue
        if f.shifts and s.shift not in f.shifts:
            continue
        if f.weekdays and s.weekday not in f.weekdays:
            continue
        if s.occupied:
            if f.courses and not any(c.lower() in s.course.lower() for c in f.courses):
                continue
            if f.persons and not any(p.lower() in s.person.lower() for p in f.persons):
                continue
        else:
            # пустые слоты отсекаются фильтрами по наполнению
            if f.courses or f.persons:
                continue
        out.append(s)
    return out


def unique_values(grids: Iterable[MonthGrid]) -> dict[str, list[str]]:
    """Справочники для фильтров формы: кабинеты, курсы, ответственные."""
    rooms: set[str] = set()
    courses: set[str] = set()
    persons: set[str] = set()
    for g in grids:
        rooms.update(g.rooms)
        for s in g.scheduled:
            if s.course:
                courses.add(s.course)
            if s.person:
                persons.add(s.person)

    def natkey(text: str) -> tuple[int, str]:
        head = re.match(r"^(\d+)", text)
        return (int(head.group(1)) if head else 999, text.lower())

    return {
        "rooms": sorted(rooms, key=natkey),
        "courses": sorted(courses, key=natkey),
        "persons": sorted(persons),
    }
