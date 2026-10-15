"""
simulator.py
============

Агрегатор фактической занятости компьютерных классов + опциональная
симуляция доборки в пустые слоты.

Вход:
    grids: list[MonthGrid]  из sheet_reader.read_months()
    filters: Filters | None
    simulate: bool          True = добор пустых слотов
    intensity: float 0–1    целевая доля заполнения пустых слотов
    seed: str               детерминизм симуляции

Выход:
    dict — структура отчёта (kpis, by_room, by_day, by_person, by_course,
    summaries и т.д.).
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Sequence

from sheet_reader import (
    EVENING,
    MORNING,
    Filters,
    MonthGrid,
    Slot,
    apply_filters,
)

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб"]
SHIFTS = (MORNING, EVENING)
ORG = "Центр непрерывного образования"


# ------------------------------------------------------------------- утилиты
def _seed(*args: Any) -> int:
    data = "|".join(str(a) for a in args).encode("utf-8")
    return int(hashlib.sha256(data).hexdigest(), 16) % (2 ** 63)


def _pct(part: float, whole: float) -> float:
    return 100.0 * part / max(whole, 1)


def _ru_date(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


# ------------------------------------------------------- точечная симуляция
def _pick_empty_slots(
    free_slots: Sequence[Slot],
    count: int,
    seed: str,
) -> list[Slot]:
    """Случайная выборка `count` пустых слотов (равномерно, детерминированно)."""
    if count <= 0 or not free_slots:
        return []
    count = min(count, len(free_slots))
    rng = random.Random(_seed(seed))
    picked = rng.sample(list(free_slots), count)
    return picked


# ------------------------------------------------------------- агрегатор
def build_report(
    grids: Sequence[MonthGrid],
    *,
    filters: Filters | None = None,
    simulate: bool = False,
    intensity: float = 0.5,
    seed: str = "",
    author: str = "",
    approver: str = "",
) -> dict[str, Any]:
    """Сводный отчёт о занятости классов по набору месячных вкладок."""
    warnings: list[str] = []
    for g in grids:
        warnings.extend(f"{g.label}: {w}" for w in g.warnings)

    all_slots = [s for g in grids for s in g.slots]
    rooms = list(dict.fromkeys(r for g in grids for r in g.rooms))
    if not all_slots or not rooms:
        return {"error": "В выбранных вкладках не найдено расписания",
                "warnings": warnings or ["проверьте названия вкладок"]}

    scheduled_real = [s for s in all_slots if s.occupied]
    free_slots = [s for s in all_slots if not s.occupied]

    # --- симуляция доборки в пустые слоты --- #
    sim_slots: list[Slot] = []
    if simulate:
        n_sim = round(intensity * len(free_slots))
        picked = _pick_empty_slots(free_slots, n_sim, seed)
        # заполняем случайными курсами/ответственными из реальных данных
        course_pool = list(Counter(s.course for s in scheduled_real if s.course))
        person_pool = list(Counter(s.person for s in scheduled_real if s.person))
        if course_pool:
            rng = random.Random(_seed(seed, len(picked)))
            for s in picked:
                c = rng.choice(course_pool)
                p = rng.choice(person_pool) if person_pool else ""
                sim_slots.append(Slot(
                    room=s.room, day=s.day, shift=s.shift,
                    raw=f"{c} ({p})" if p else c,
                    course=c, person=p, time_note="", uncertain=False,
                    weekday_label=s.weekday_label, simulated=True,
                ))
            if not sim_slots:
                warnings.append("симуляция не добавила занятий (пустой справочник курсов)")

    # --- применяем фильтры --- #
    f = filters or Filters()
    all_sched = scheduled_real + sim_slots
    visible = apply_filters(all_sched, f)
    days = sorted({s.day for s in all_slots})
    period_from, period_to = days[0], days[-1]
    rooms_in_scope = [r for r in rooms if not f.rooms or r in f.rooms]
    shifts_in_scope = f.shifts if f.shifts else SHIFTS
    capacity = len(days) * len(rooms_in_scope) * len(shifts_in_scope)
    occupied = len(visible)
    occupancy = _pct(occupied, capacity)
    shifts_in_scope = f.shifts if f.shifts else SHIFTS
    capacity = len(days) * len(rooms_in_scope) * len(shifts_in_scope)
    occupied = len(visible)
    occupancy = _pct(occupied, capacity)

    # --- разбивка по кабинетам --- #
    occupied_set = {(s.room, s.day, s.shift) for s in all_sched}
    by_room: list[dict] = []
    for room in rooms_in_scope:
        room_sched = [s for s in visible if s.room == room]
        cap_r = len(days) * len(shifts_in_scope)
        occ_r = len(room_sched)
        idle_d = sum(1 for d in days
                     if not any((room, d, sh) in occupied_set
                                for sh in shifts_in_scope))
        courses = Counter(s.course for s in room_sched if s.course)
        persons = Counter(s.person for s in room_sched if s.person)
        by_room.append({
            "room": room,
            "capacity": cap_r,
            "occupied": occ_r,
            "free": max(0, cap_r - occ_r),
            "occupancy": _pct(occ_r, cap_r),
            "idle_days": idle_d,
            "top_course": courses.most_common(1)[0][0] if courses else "—",
            "top_person": persons.most_common(1)[0][0] if persons else "—",
        })
    by_room.sort(key=lambda r: (-r["occupancy"], r["room"]))

    # --- разбивка по дням --- #
    by_day: list[dict] = []
    for d in days:
        occ_d = sum(1 for s in visible if s.day == d)
        cap_d = len(rooms_in_scope) * len(f.shifts) if f.shifts else len(rooms_in_scope) * 2
        wd = next((s.weekday_label for s in visible if s.day == d and s.weekday_label),
                  WEEKDAYS[d.weekday()])
        by_day.append({"day": d, "weekday": wd,
                       "capacity": cap_d, "occupied": occ_d,
                       "occupancy": _pct(occ_d, cap_d)})

    # --- разбивка по сменам --- #
    shifts_in_scope = f.shifts if f.shifts else SHIFTS
    by_shift: list[dict] = []
    for shift in shifts_in_scope:
        occ_s = sum(1 for s in visible if s.shift == shift)
        cap_s = len(days) * len(rooms_in_scope)
        by_shift.append({"shift": shift, "capacity": cap_s,
                         "occupied": occ_s, "occupancy": _pct(occ_s, cap_s)})

    # --- разбивка по дням недели --- #
    by_weekday: list[dict] = []
    for wd in WEEKDAYS:
        day_list = [d for d in days if WEEKDAYS[d.weekday()] == wd]
        if not day_list:
            continue
        occ_wd = sum(1 for s in visible if WEEKDAYS[s.day.weekday()] == wd)
        cap_wd = len(day_list) * len(rooms_in_scope) * len(f.shifts) if f.shifts else len(day_list) * len(rooms_in_scope) * 2
        by_weekday.append({"weekday": wd, "days": len(day_list),
                           "capacity": cap_wd, "occupied": occ_wd,
                           "occupancy": _pct(occ_wd, cap_wd)})

    # --- ответственные и курсы --- #
    by_person, by_course = _group(visible)

    # --- свободные окна (после симуляции!) --- #
    free_effective = [
        {"room": r, "day": d, "shift": sh}
        for r in rooms_in_scope for d in days for sh in shifts_in_scope
        if (r, d, sh) not in occupied_set
    ]
    free_by_room = Counter(x["room"] for x in free_effective)
    idle_day_pairs = [
        {"room": r, "day": d}
        for r in rooms_in_scope for d in days
        if not any((r, d, sh) in occupied_set for sh in SHIFTS)
    ]

    # --- сводные числа --- #
    peak = max(by_day, key=lambda x: x["occupied"]) if by_day else None
    low = min((x for x in by_day if x["capacity"]), key=lambda x: x["occupied"],
              default=None)
    busiest = max(by_room, key=lambda r: r["occupancy"]) if by_room else None
    quietest = min(by_room, key=lambda r: r["occupancy"]) if by_room else None

    kpis = [
        {"label": "Кабинетов в отчёте", "value": len(rooms_in_scope), "unit": "шт", "kind": "int"},
        {"label": "Учебных дней", "value": len(days), "unit": "дн", "kind": "int"},
        {"label": "Фонд слотов (кабинет × смена)", "value": capacity, "unit": "", "kind": "int"},
        {"label": "Проведено занятий", "value": occupied, "unit": "пар", "kind": "int"},
        {"label": "Занятость фонда", "value": occupancy, "unit": "%", "kind": "percent"},
        {"label": "Простои", "value": max(0, capacity - occupied),
         "unit": "смен", "kind": "int",
         "delta": _pct(max(0, capacity - occupied), capacity)},
    ]

    summaries = _summaries(
        grids=grids, days=days, rooms=rooms_in_scope,
        capacity=capacity, occupied=occupied,
        real=len([s for s in all_sched if not s.simulated]),
        sim=len([s for s in all_sched if s.simulated]),
        simulate=simulate, intensity=intensity,
        peak=peak, low=low, busiest=busiest, quietest=quietest,
        free_total=max(0, capacity - occupied),
        idle_days=len(idle_day_pairs),
        occupancy=occupancy,
        by_shift=by_shift,
        by_person=by_person,
        by_course=by_course,
    )

    return {
        "kind": "occupancy",
        "org": ORG,
        "months": [g.label for g in grids],
        "months_label": " · ".join(g.label for g in grids),
        "tabs": [g.title.strip() for g in grids],
        "period_from": period_from,
        "period_to": period_to,
        "days": days,
        "rooms": rooms_in_scope,
        "capacity": capacity,
        "occupied": occupied,
        "occupied_real": len([s for s in all_sched if not s.simulated]),
        "occupied_sim": len([s for s in all_sched if s.simulated]),
        "occupancy": occupancy,
        "idle": max(0, capacity - occupied),
        "idle_pct": _pct(max(0, capacity - occupied), capacity),
        "kpis": kpis,
        "by_room": by_room,
        "by_day": by_day,
        "by_shift": by_shift,
        "by_weekday": by_weekday,
        "by_person": by_person,
        "by_course": by_course,
        "free_by_room": free_by_room,
        "idle_days": idle_day_pairs,
        "peak_day": peak,
        "low_day": low,
        "busiest_room": busiest,
        "quietest_room": quietest,
        "summaries": summaries,
        "author": author or "—",
        "approver": approver or "—",
        "generated_at": datetime.now(),
        "warnings": warnings,
        "simulated": bool(sim_slots),
        "intensity": intensity if simulate else 0.0,
        "filter_note": _filter_note(f),
    }


# ------------------------------------------------------------------- подмоги
def _person_key(s: Slot) -> str:
    return s.person


def _course_key(s: Slot) -> str:
    return s.course


def _group(slots: Sequence[Slot]) -> tuple[list[dict], list[dict]]:
    """(по ответственным, по курсам) — кол-во пар, классы, доля."""
    def _by(key) -> list[dict]:
        pairs: Counter = Counter()
        rooms: dict[str, set[str]] = defaultdict(set)
        partners: dict[str, set[str]] = defaultdict(set)
        for s in slots:
            name = key(s)
            if not name:
                continue
            pairs[name] += 1
            rooms[name].add(s.room)
            other = s.person if key is _person_key else s.course
            if other:
                partners[name].add(other)
        total = sum(pairs.values())
        return [
            {"name": name, "pairs": count, "share": _pct(count, total),
             "rooms": tuple(sorted(rooms[name])),
             "extra_count": len(partners[name])}
            for name, count in pairs.most_common()
        ]

    return _by(_person_key), _by(_course_key)


def _filter_note(f: Filters) -> str:
    parts: list[str] = []
    if f.rooms:
        parts.append("классы: " + ", ".join(f.rooms))
    if f.shifts:
        parts.append("смены: " + ", ".join(s.split(" ")[0].lower() for s in f.shifts))
    if f.weekdays:
        parts.append("дни недели: " + ", ".join(f.weekdays))
    if f.courses:
        parts.append("курсы: " + ", ".join(f.courses[:6]) +
                     ("…" if len(f.courses) > 6 else ""))
    if f.persons:
        parts.append("ответственные: " + ", ".join(f.persons[:6]) +
                     ("…" if len(f.persons) > 6 else ""))
    return " · ".join(parts) if parts else "без фильтров (все классы и смены)"


def _summaries(
    grids, days, rooms, capacity, occupied, real, sim, simulate, intensity,
    peak, low, busiest, quietest, free_total, idle_days, occupancy,
    by_shift, by_person, by_course,
) -> list[str]:
    out: list[str] = []
    out.append(
        f"Сводный отчёт построен по {len(grids)} месячным вкладкам "
        f"({', '.join(g.label for g in grids)}), период — "
        f"{_ru_date(days[0])} — {_ru_date(days[-1])}, учебных дней {len(days)}. "
        f"Фонд рабочего времени {len(rooms)} компьютерных классов составляет "
        f"{capacity} слотов (кабинет × смена). Фактически проведено {occupied} "
        f"занятий, занятость фонда — {occupancy:.1f} %."
    )

    if simulate:
        out.append(
            f"Из {occupied} занятий {real} взято из расписания таблицы как "
            f"факт, {sim} добавлено симуляцией в ранее пустые слоты "
            f"(заданная плотность доборки {intensity:.0%}). "
            f"Отчёт в режиме «факт + симуляция» следует согласовывать перед "
            f"использованием как официального документа."
        )
    else:
        out.append(
            f"Все {occupied} занятий — фактические записи из вкладок расписания, "
            f"режим симуляции был выключен. Свободных слотов осталось "
            f"{free_total} ({_pct(free_total, capacity):.1f} % фонда), "
            f"полностью свободных дней по кабинетам — {idle_days}."
        )

    if peak and low:
        out.append(
            f"Пиковая загрузка приходится на {peak['weekday']} "
            f"{_ru_date(peak['day'])} — {peak['occupied']} занятий из "
            f"{peak['capacity']} возможных ({peak['occupancy']:.1f} %). Наиболее "
            f"разгруженный день — {low['weekday']} {_ru_date(low['day'])} "
            f"({low['occupied']} занятий, {low['occupancy']:.1f} %)."
        )

    if busiest and quietest:
        out.append(
            f"Самый загруженный класс — {busiest['room']} ({busiest['occupancy']:.1f} % "
            f"фонда, {busiest['occupied']} занятий), самый свободный — "
            f"{quietest['room']} ({quietest['occupancy']:.1f} %, свободных смен "
            f"{quietest['free']}). Основное наполнение класса {busiest['room']} — "
            f"«{busiest['top_course']}»"
            + (f", ответственный {busiest['top_person']}." if busiest['top_person'] != "—" else ".")
        )

    if len(by_shift) == 2:
        morning = next((s for s in by_shift if "Утро" in s["shift"]), None)
        evening = next((s for s in by_shift if "Вечер" in s["shift"]), None)
        if morning and evening:
            lead = "утренняя" if morning["occupied"] >= evening["occupied"] else "вечерняя"
            out.append(
                f"Утренние смены (9.30–14.40) загружены на {morning['occupancy']:.1f} % "
                f"({morning['occupied']} занятий), вечерние (15.00–19.50) — на "
                f"{evening['occupancy']:.1f} % ({evening['occupied']}). "
                f"Доминирует {lead} смена; резерв второй смены — основной источник "
                f"дополнительных слотов без расширения материальной базы."
            )

    if by_person:
        top = by_person[0]
        out.append(
            f"Среди ответственных лидирует {top['name']} — {top['pairs']} занятий "
            f"({top['share']:.1f} % всех проведённых) в {len(top['rooms'])} "
            f"класс(ах). Крупнейшие направления: "
            + ", ".join(f"«{c['name']}» ({c['pairs']})" for c in by_course[:3]) + "."
        )
    return out
