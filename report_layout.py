"""
report_layout.py
================

Компоновка сводного отчёта о занятости компьютерных классов:
Word-подобный документ из данных simulator.build_report + текстовое превью
для десктопного интерфейса.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from document_builder import (
    COLOR_INK,
    COLOR_MUTED,
    COLOR_NEGATIVE,
    COLOR_POSITIVE,
    COLOR_TEXT,
    NF_INT,
    NF_PERCENT,
    ReportDocument,
    short_date,
)

MAX_ROOM_ROWS = 24
MAX_PERSON_ROWS = 18
MAX_DAY_ROWS = 70


# ------------------------------------------------------------- подписи
def _ru(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _period(report: dict[str, Any]) -> str:
    return f"{_ru(report['period_from'])} — {_ru(report['period_to'])}"


def _mode(report: dict[str, Any]) -> str:
    if report.get("simulated"):
        return f"факт + симуляция (плотность доборки {report['intensity']:.0%})"
    return "только фактические данные таблицы"


def _pct_text(value: float) -> str:
    return f"{value:.1f} %"


def _delta_for_occupancy(report: dict[str, Any]) -> float:
    """Отклонение фактической занятости от «нормы» в 50 % фонда."""
    return report["occupancy"] - 50.0


# ------------------------------------------------------------- документ
def render_report(doc: ReportDocument, report: dict[str, Any]) -> None:
    if report.get("error"):
        _render_error(doc, report)
        return

    doc.page()

    # ---- шапка ----------------------------------------------------------- #
    doc.spacer(12)
    doc.text(report["org"], size=12, bold=True, color=COLOR_INK,
             align="CENTER", height=20)
    doc.text("Мониторинг использования компьютерных классов",
             size=8, color=COLOR_MUTED, align="CENTER", height=14)
    doc.spacer(14)

    # ---- титул ----------------------------------------------------------- #
    doc.text("ОТЧЁТ", size=22, bold=True, color=COLOR_INK, align="CENTER", height=34)
    doc.text("о занятости компьютерных классов", size=13, bold=True,
             color=COLOR_INK, align="CENTER", height=22)
    doc.text(f"за период {_period(report)}", size=11, color=COLOR_TEXT,
             align="CENTER", height=20)
    doc.spacer(6)
    doc.line(weight=4)
    doc.spacer(10)

    # ---- реквизиты отчёта ------------------------------------------------ #
    room_names = ", ".join(report["rooms"])
    meta = [
        ("Периоды", ", ".join(m.capitalize() for m in report["months"])),
        ("Даты", _period(report)),
        ("Учебных дней", f"{report['capacity_days'] if 'capacity_days' in report else len(report['days'])}"),
        ("Компьютерных классов", f"{len(report['rooms'])} ({room_names})"),
        ("Источник данных", " · ".join(report["tabs"])),
        ("Режим формирования", _mode(report)),
        ("Фильтры", report["filter_note"]),
        ("Составил", report["author"]),
        ("Согласовал (заместитель директора)", report["approver"]),
        ("Дата формирования", report["generated_at"].strftime("%d.%m.%Y %H:%M")),
    ]
    for label, value in meta:
        doc.kv(f"{label}:", str(value), label_span=3)
    doc.spacer(6)

    if report.get("warnings"):
        doc.paragraph("Примечания: " + "; ".join(report["warnings"]))
        doc.spacer(10)

    # ---- 1. ключевые показатели ------------------------------------------ #
    doc.heading("1. Ключевые показатели")
    kpi_rows = []
    for k in report["kpis"]:
        value = k["value"]
        kpi_rows.append([k["label"], round(float(value), 1),
                         k.get("unit", "") or "—"])
    kpi_table = doc.table(
        ["Показатель", "Значение", "Ед."],
        kpi_rows,
        spans=[4, 2, 1],
        aligns=["LEFT", "RIGHT", "CENTER"],
        formats=[None, NF_PERCENT, None],
    )
    for index, k in enumerate(report["kpis"]):
        row = kpi_table.first_body + index
        c1, c2 = kpi_table.column_span(1)
        kind = k["kind"]
        doc.style(
            row, c1, row, c2, bold=True, size=11,
            fg=COLOR_POSITIVE if (kind == "percent" and k["value"] >= 50) else
               (COLOR_NEGATIVE if kind == "percent" and k["value"] < 20 else COLOR_TEXT),
            align="RIGHT",
            number_format=NF_PERCENT if kind == "percent" else NF_INT,
        )
    doc.spacer(8)
    doc.paragraph(
        f"Справка: фонд рабочего времени рассчитан как «число классов × учебных "
        f"дней × 2 смены» и составляет {report['capacity']} слотов. Занятость "
        f"{_pct_text(report['occupancy'])} означает, что {report['occupied']} из "
        f"{report['capacity']} возможных слотов занято занятиями; простои — "
        f"{report['idle']} смен ({_pct_text(report['idle_pct'])})."
    )
    doc.spacer(14)

    # ---- 2. загрузка по классам ------------------------------------------ #
    doc.heading("2. Загрузка компьютерных классов")
    rooms = report["by_room"][:MAX_ROOM_ROWS]
    room_rows = [
        [r["room"], r["occupied"], r["capacity"], round(r["occupancy"], 1),
         r["free"], r["idle_days"], r["top_course"]]
        for r in rooms
    ]
    total_row = [
        "Итого", report["occupied"], report["capacity"],
        round(report["occupancy"], 1), report["idle"],
        len(report["idle_days"]), "—",
    ]
    room_table = doc.table(
        ["Класс", "Занято", "Фонд", "Занятость", "Свободно", "Прост. дней",
         "Основной курс"],
        room_rows,
        spans=[1, 1, 1, 1, 1, 1, 1],
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "LEFT"],
        formats=[None, NF_INT, NF_INT, NF_PERCENT, NF_INT, NF_INT, None],
        total_row=total_row,
    )
    for index, r in enumerate(rooms):
        row = room_table.first_body + index
        c1, c2 = room_table.column_span(3)
        doc.style(row, c1, row, c2, bold=True, align="RIGHT",
                  fg=COLOR_POSITIVE if r["occupancy"] >= 50 else
                     (COLOR_NEGATIVE if r["occupancy"] < 20 else COLOR_TEXT),
                  number_format=NF_PERCENT)
        c1, c2 = room_table.column_span(6)
        doc.style(row, c1, row, c2, size=9, align="LEFT", valign="MIDDLE")

    # график занятости по классам
    domain = (room_table.header_row, room_table.column_anchor(0),
              room_table.last_body, room_table.column_anchor(0))
    series = (room_table.header_row, room_table.column_anchor(1),
              room_table.last_body, room_table.column_anchor(1))
    anchor = doc.reserve(250)
    doc.chart(title="Проведённые занятия по классам", chart_type="COLUMN",
              domain=domain, series=[series], anchor_row=anchor,
              height=240, width=640, legend="NO_LEGEND")
    doc.spacer(14)

    # ---- 3. динамика по дням --------------------------------------------- #
    doc.heading("3. Динамика загрузки по дням")
    days = report["by_day"][:MAX_DAY_ROWS]
    day_rows = [[short_date(d["day"]), d["weekday"].upper(), d["occupied"],
                 d["capacity"], round(d["occupancy"], 1)] for d in days]
    peak = report["peak_day"]
    low = report["low_day"]
    day_table = doc.table(
        ["Дата", "Д/н", "Занято", "Фонд", "Занятость"],
        day_rows,
        spans=[2, 1, 1, 1, 2],
        aligns=["LEFT", "CENTER", "RIGHT", "RIGHT", "RIGHT"],
        formats=[None, None, NF_INT, NF_INT, NF_PERCENT],
        total_row=["Итого", "—", report["occupied"], report["capacity"],
                   round(report["occupancy"], 1)],
    )
    for index, d in enumerate(days):
        row = day_table.first_body + index
        c1, c2 = day_table.column_span(4)
        doc.style(row, c1, row, c2, align="RIGHT", number_format=NF_PERCENT,
                  bold=d["occupied"] > 0,
                  fg=COLOR_MUTED if d["occupied"] == 0 else COLOR_TEXT)
    domain = (day_table.header_row, day_table.column_anchor(0),
              day_table.last_body, day_table.column_anchor(0))
    series = (day_table.header_row, day_table.column_anchor(2),
              day_table.last_body, day_table.column_anchor(2))
    anchor = doc.reserve(250)
    doc.chart(title="Проведённые занятия по дням", chart_type="AREA",
              domain=domain, series=[series], anchor_row=anchor,
              height=240, width=640, legend="NO_LEGEND")
    if peak and low:
        doc.spacer(6)
        doc.paragraph(
            f"Пик загрузки — {peak['weekday']} {_ru(peak['day'])} "
            f"({peak['occupied']} занятий, {_pct_text(peak['occupancy'])}); "
            f"минимум — {low['weekday']} {_ru(low['day'])} "
            f"({low['occupied']} занятий)."
        )
    doc.spacer(14)

    # ---- 4. смены и дни недели ------------------------------------------- #
    doc.heading("4. Распределение по сменам и дням недели")
    shift_rows = [
        [s["shift"], s["occupied"], s["capacity"], round(s["occupancy"], 1)]
        for s in report["by_shift"]
    ]
    doc.table(
        ["Смена", "Занято", "Фонд", "Занятость"],
        shift_rows,
        spans=[3, 1, 1, 2],
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT"],
        formats=[None, NF_INT, NF_INT, NF_PERCENT],
    )
    doc.spacer(8)
    wd_rows = [
        [w["weekday"].upper(), w["days"], w["occupied"], w["capacity"],
         round(w["occupancy"], 1)]
        for w in report["by_weekday"]
    ]
    wd_table = doc.table(
        ["День недели", "Дней", "Занято", "Фонд", "Занятость"],
        wd_rows,
        spans=[1, 1, 2, 1, 2],
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"],
        formats=[None, NF_INT, NF_INT, NF_INT, NF_PERCENT],
    )
    for index, w in enumerate(wd_rows):
        row = wd_table.first_body + index
        c1, c2 = wd_table.column_span(4)
        doc.style(row, c1, row, c2, align="RIGHT", number_format=NF_PERCENT,
                  bold=w[4] > 0)
    doc.spacer(14)

    # ---- 5. ответственные и курсы ----------------------------------------- #
    doc.heading("5. Нагрузка ответственных и направления занятий")
    doc.text("5.1. Ответственные лица", size=10, bold=True, color=COLOR_INK,
             height=20)
    persons = report["by_person"][:MAX_PERSON_ROWS]
    doc.table(
        ["Ответственный", "Пар", "Доля", "Классов"],
        [[p["name"], p["pairs"], round(p["share"], 1), len(p["rooms"])]
         for p in persons],
        spans=[3, 1, 1, 2],
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT"],
        formats=[None, NF_INT, NF_PERCENT, NF_INT],
    )
    doc.spacer(10)
    doc.text("5.2. Направления (курсы, мероприятия)", size=10, bold=True,
             color=COLOR_INK, height=20)
    courses = report["by_course"][:MAX_PERSON_ROWS]
    doc.table(
        ["Направление", "Пар", "Доля", "Классов"],
        [[c["name"], c["pairs"], round(c["share"], 1), len(c["rooms"])]
         for c in courses],
        spans=[3, 1, 1, 2],
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT"],
        formats=[None, NF_INT, NF_PERCENT, NF_INT],
    )
    doc.spacer(14)

    # ---- 6. свободные окна ------------------------------------------------- #
    doc.heading("6. Свободные окна и резерв загрузки")
    doc.paragraph(
        f"Свободных слотов за период — {report['idle']} "
        f"({_pct_text(report['idle_pct'])} фонда). Полностью свободных "
        f"сочетаний «класс × день» — {len(report['idle_days'])}. Ниже — "
        f"классы с наибольшим числом свободных смен: их можно использовать "
        f"для дополнительного набора без расширения материальной базы."
    )
    doc.spacer(6)
    free_rows = [[room, count] for room, count in
                 report["free_by_room"].most_common(MAX_ROOM_ROWS)]
    doc.table(
        ["Класс", "Свободных смен"],
        free_rows,
        spans=[5, 2],
        aligns=["LEFT", "RIGHT"],
        formats=[None, NF_INT],
    )
    doc.spacer(24)

    # ---- 7. аналитическая записка ----------------------------------------- #
    doc.heading("7. Аналитическая записка")
    for paragraph in report["summaries"]:
        doc.paragraph(paragraph)
        doc.spacer(6)
    doc.spacer(24)

    # ---- подписи ----------------------------------------------------------- #
    doc.signature([
        ("Составил", report["author"]),
        ("Согласовал", report["approver"]),
        ("Дата", report["generated_at"].strftime("%d.%m.%Y")),
    ])
    doc.spacer(16)
    doc.footer(
        f"Сформировано автоматически {report['generated_at']:%d.%m.%Y %H:%M} · "
        f"источник: {' / '.join(report['tabs'])} · режим: {_mode(report)}"
    )


def _render_error(doc: ReportDocument, report: dict[str, Any]) -> None:
    doc.page()
    doc.spacer(40)
    doc.text("Отчёт не сформирован", size=16, bold=True, color=COLOR_NEGATIVE,
             align="CENTER", height=28)
    doc.spacer(10)
    doc.text(str(report.get("error", "")), size=11, align="CENTER", height=20)
    for warning in report.get("warnings", []):
        doc.text(str(warning), size=10, color=COLOR_MUTED, align="CENTER", height=18)


# ------------------------------------------------------------- текстовое превью
def render_preview(report: dict[str, Any]) -> str:
    if report.get("error"):
        return ("─" * 78) + f"\n{report['error']}\n" + "\n".join(
            "  " + str(w) for w in report.get("warnings", []))

    line = "─" * 78
    out: list[str] = [line]
    out.append(report["org"].center(78))
    out.append("Мониторинг использования компьютерных классов".center(78))
    out.append("")
    out.append("ОТЧЁТ".center(78))
    out.append("о занятости компьютерных классов".center(78))
    out.append(_period(report).center(78))
    out.append(line)

    out.append(f"{'Периоды:':<26}{', '.join(m.capitalize() for m in report['months'])}")
    out.append(f"{'Учебных дней:':<26}{len(report['days'])}")
    out.append(f"{'Классов:':<26}{len(report['rooms'])} — {', '.join(report['rooms'])}")
    out.append(f"{'Вкладки-источники:':<26}{' · '.join(report['tabs'])}")
    out.append(f"{'Режим:':<26}{_mode(report)}")
    out.append(f"{'Фильтры:':<26}{report['filter_note']}")
    for w in report.get("warnings", []):
        out.append(f"{'':<26}⚠ {w}")
    out.append(line)

    out.append("1. КЛЮЧЕВЫЕ ПОКАЗАТЕЛИ")
    for k in report["kpis"]:
        value = k["value"]
        text = (f"{value:.1f} {k['unit']}".strip() if k["kind"] == "percent"
                else f"{int(value):,} {k['unit']}".replace(",", " ").strip())
        out.append(f"  {k['label']:<38}{text:>26}")
    out.append(line)

    out.append("2. ЗАГРУЗКА КЛАССОВ")
    out.append(f"  {'Класс':<14}{'Занято':>8}{'Фонд':>8}{'Занят.':>9}"
               f"{'Своб.':>8}{'Прост.':>8}  Основной курс")
    for r in report["by_room"][:14]:
        out.append(
            f"  {r['room']:<14}{r['occupied']:>8}{r['capacity']:>8}"
            f"{r['occupancy']:>8.1f}%{r['free']:>8}{r['idle_days']:>8}  "
            f"{r['top_course'][:26]}"
        )
    if len(report["by_room"]) > 14:
        out.append(f"  … и ещё {len(report['by_room']) - 14} кл.")
    out.append(
        f"  {'ИТОГО':<14}{report['occupied']:>8}{report['capacity']:>8}"
        f"{report['occupancy']:>8.1f}%{report['idle']:>8}"
        f"{len(report['idle_days']):>8}"
    )
    out.append("  [ график занятий по классам ]")
    out.append(line)

    out.append("3. ДИНАМИКА ПО ДНЯМ")
    days = report["by_day"]
    shown = days[:12]
    for d in shown:
        bar = "█" * max(0, round(d["occupancy"] / 4)) if d["occupied"] else "·"
        out.append(f"  {short_date(d['day']):<9}{d['weekday'].upper():<5}"
                   f"{d['occupied']:>4}/{d['capacity']:<4}"
                   f"{d['occupancy']:>7.1f}%  {bar}")
    if len(days) > 12:
        out.append(f"  … и ещё {len(days) - 12} дн.")
    out.append("  [ график загрузки по дням ]")
    out.append(line)

    out.append("4. СМЕНЫ И ДНИ НЕДЕЛИ")
    for s in report["by_shift"]:
        out.append(f"  {s['shift']:<24}{s['occupied']:>5}/{s['capacity']:<5}"
                   f"{s['occupancy']:>7.1f}%")
    for w in report["by_weekday"]:
        out.append(f"  {w['weekday'].upper():<24}{w['occupied']:>5}/{w['capacity']:<5}"
                   f"{w['occupancy']:>7.1f}%   (дней {w['days']})")
    out.append(line)

    out.append("5. НАГРУЗКА ОТВЕТСТВЕННЫХ / НАПРАВЛЕНИЙ")
    for p in report["by_person"][:8]:
        out.append(f"  {p['name']:<28}{p['pairs']:>4} пар{p['share']:>8.1f}%"
                   f"   классов {len(p['rooms'])}")
    out.append("  — направления —")
    for c in report["by_course"][:8]:
        out.append(f"  {c['name']:<28}{c['pairs']:>4} пар{c['share']:>8.1f}%"
                   f"   классов {len(c['rooms'])}")
    out.append(line)

    out.append("6. СВОБОДНЫЕ ОКНА И РЕЗЕРВ")
    out.append(f"  Свободных слотов: {report['idle']} "
               f"({report['idle_pct']:.1f} % фонда)")
    out.append(f"  Полностью свободных «класс × день»: {len(report['idle_days'])}")
    from collections import Counter
    free_data = report["free_by_room"]
    if not isinstance(free_data, Counter):
        free_data = Counter(free_data)
    for room, count in free_data.most_common(6):
        out.append(f"    {room:<14}{count:>4} свободных смен")
    out.append(line)

    out.append("7. АНАЛИТИЧЕСКАЯ ЗАПИСКА")
    for paragraph in report["summaries"]:
        out.extend(f"  {ln}" for ln in _wrap(paragraph, 74))
        out.append("")
    out.append(line)
    out.append(f"  Составил: {report['author']:<26}"
               f"Согласовал: {report['approver']}")
    out.append(line)
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if len(current) + len(word) + 1 > width:
            lines.append(current.strip())
            current = ""
        current += word + " "
    if current.strip():
        lines.append(current.strip())
    return lines
