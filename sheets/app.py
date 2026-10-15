"""
app.py
======

Tkinter-интерфейс:
  1. Подключение к таблице → список месячных вкладок
  2. Мультивыбор месяцев → загрузка данных и фильтров
  3. Фильтры (классы чекбоксами, смены, курсы/ответственные текстом)
  4. Режим: только факт / факт + симуляция (плотность, семя)
  5. Формирование → превью + выгрузка в Google Sheets
"""
from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from google_sheets_client import GoogleSheetsClient
from sheet_reader import Filters, MORNING, EVENING, list_months, read_months, unique_values
from simulator import build_report
from report_layout import render_report, render_preview
from document_builder import ReportDocument
from sheet_writer import ReportWriter

CFG = json.loads(Path("config.json").read_text(encoding="utf-8"))
CREDENTIALS = CFG["credentials_path"]
SPREADSHEET_ID = CFG["spreadsheet_id"]


# ------------------------------------------------------------------- App
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Отчёт о занятости компьютерных классов")
        self.geometry("1500x950")
        self._client: GoogleSheetsClient | None = None
        self._months_meta: list[dict] = []
        self._current_report: dict | None = None
        self._room_vars: dict[str, tk.BooleanVar] = {}
        self._shift_vars: dict[str, tk.BooleanVar] = {}
        self._build_ui()

    # ================================================================ UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(1, weight=1)

        # ---- шапка ----
        hdr = ttk.Frame(self)
        hdr.grid(row=0, column=0, columnspan=2, sticky="we", pady=(6, 6))
        hdr.columnconfigure(1, weight=1)

        self._btn_conn = ttk.Button(hdr, text="🔌 Подключиться",
                                     command=self._do_connect)
        self._btn_conn.grid(row=0, column=0, padx=3)
        self._lbl_status = ttk.Label(hdr, text="Не подключено",
                                      foreground="#999")
        self._lbl_status.grid(row=0, column=1, padx=6, sticky="w")

        self._btn_gen = ttk.Button(hdr, text="▶ Сформировать",
                                    command=self._do_generate, state="disabled")
        self._btn_gen.grid(row=0, column=2, padx=3)
        self._btn_write = ttk.Button(
            hdr, text="📤 Выгрузить в Sheets",
            command=self._do_write, state="disabled")
        self._btn_write.grid(row=0, column=3, padx=3)

        # ---- левая панель ----
        left = ttk.LabelFrame(self, text="Настройки")
        left.grid(row=1, column=0, sticky="nswe",
                   pady=(0, 6), padx=(6, 4))
        left.columnconfigure(0, weight=1)

        # Месяцы
        ttk.Label(left, text="Месяцы:").grid(
            row=0, column=0, sticky="w", padx=4, pady=2)
        self._lb_months = tk.Listbox(
            left, selectmode="multiple", height=6, font=("Segoe UI", 9))
        self._lb_months.grid(
            row=1, column=0, sticky="we", padx=4, pady=2)

        ttk.Button(left, text="Загрузить фильтры",
                    command=self._do_load_filters).grid(
            row=2, column=0, padx=4, pady=4)

        # Классы (чекбоксы)
        self._frm_rooms = ttk.LabelFrame(left, text="Классы")
        self._frm_rooms.grid(
            row=3, column=0, sticky="we", padx=4, pady=4)
        self._frm_rooms.columnconfigure(0, weight=1)

        # Смены (чекбоксы)
        self._frm_shifts = ttk.LabelFrame(left, text="Смены")
        self._frm_shifts.grid(
            row=4, column=0, sticky="we", padx=4, pady=4)
        self._frm_shifts.columnconfigure(0, weight=1)

        # Курс / ответственный (текст)
        f_text = ttk.Frame(left)
        f_text.grid(row=5, column=0, sticky="we", padx=4, pady=4)
        f_text.columnconfigure(1, weight=1)
        ttk.Label(f_text, text="Курс (через запятую):").grid(
            row=0, column=0, sticky="w")
        self._entry_courses = ttk.Entry(f_text)
        self._entry_courses.grid(
            row=0, column=1, sticky="we", padx=4)
        ttk.Label(
            f_text, text="Ответственный (через запятую):").grid(
            row=1, column=0, sticky="w")
        self._entry_persons = ttk.Entry(f_text)
        self._entry_persons.grid(
            row=1, column=1, sticky="we", padx=4)

        # Режим
        f_mode = ttk.LabelFrame(left, text="Режим")
        f_mode.grid(row=6, column=0, sticky="we", padx=4, pady=4)
        self._mode_var = tk.StringVar(value="fact")
        ttk.Radiobutton(f_mode, text="Только факт",
                         variable=self._mode_var,
                         value="fact").grid(
            row=0, column=0, sticky="w", padx=6)
        ttk.Radiobutton(f_mode, text="Факт + симуляция",
                         variable=self._mode_var,
                         value="sim").grid(
            row=0, column=1, sticky="w", padx=6)

        f_sim = ttk.Frame(f_mode)
        f_sim.grid(row=1, column=0, columnspan=2,
                    sticky="w", padx=6)
        f_sim.columnconfigure(1, weight=1)
        ttk.Label(f_sim, text="Плотность:").grid(
            row=0, column=0, sticky="w")
        self._sim_intensity = tk.DoubleVar(value=0.5)
        ttk.Spinbox(f_sim, from_=0.05, to=1.0, increment=0.05,
                     width=6,
                     textvariable=self._sim_intensity).grid(
            row=0, column=1, padx=4)
        ttk.Label(f_sim, text="Семя:").grid(
            row=0, column=2, sticky="w")
        self._sim_seed = ttk.Entry(f_sim, width=10)
        self._sim_seed.grid(row=0, column=3, padx=4)

        f_auth = ttk.Frame(f_mode)
        f_auth.grid(row=2, column=0, columnspan=2,
                     sticky="w", padx=6)
        f_auth.columnconfigure(1, weight=1)
        ttk.Label(f_auth, text="Составил:").grid(
            row=0, column=0, sticky="w")
        self._entry_author = ttk.Entry(f_auth, width=14)
        self._entry_author.grid(row=0, column=1, padx=4)
        ttk.Label(f_auth, text="Согласовал:").grid(
            row=0, column=2, sticky="w")
        self._entry_approver = ttk.Entry(f_auth, width=14)
        self._entry_approver.grid(row=0, column=3, padx=4)

        # ---- правая панель: превью ----
        right = ttk.LabelFrame(self, text="Превью отчёта")
        right.grid(row=1, column=1, sticky="nswe",
                    pady=(0, 6), padx=(4, 6))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._txt_preview = tk.Text(
            right, wrap="word", font=("Consolas", 9),
            bg="#FAFAFA", padx=8, pady=8)
        self._txt_preview.grid(row=0, column=0, sticky="nswe")
        sb = ttk.Scrollbar(
            right, orient="vertical",
            command=self._txt_preview.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._txt_preview.configure(yscrollcommand=sb.set)

        # ---- журнал ----
        f_log = ttk.LabelFrame(self, text="Журнал")
        f_log.grid(row=2, column=0, columnspan=2,
                    sticky="we", pady=(0, 6))
        f_log.columnconfigure(0, weight=1)
        f_log.rowconfigure(0, weight=1)

        self._txt_log = tk.Text(f_log, wrap="word",
                                 font=("Consolas", 9),
                                 height=4, bg="#FAFAFA",
                                 padx=6, pady=4)
        self._txt_log.grid(row=0, column=0, sticky="nswe")
        lsb = ttk.Scrollbar(f_log, orient="vertical",
                             command=self._txt_log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self._txt_log.configure(yscrollcommand=lsb.set)

    # ============================================================= helpers
    def _log(self, msg: str) -> None:
        self._txt_log.insert("end",
                             f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self._txt_log.see("end")

    def _show_preview(self, report: dict) -> None:
        self._txt_preview.delete("1.0", "end")
        self._txt_preview.insert("1.0", render_preview(report))
        self._btn_write.configure(state="normal")

    # =========================================================== подключение
    def _do_connect(self) -> None:
        self._btn_conn.configure(state="disabled")
        self._lbl_status.configure(text="Подключение…",
                                    foreground="#888")
        threading.Thread(target=self._connect,
                          daemon=True).start()

    def _connect(self) -> None:
        try:
            client = GoogleSheetsClient(
                CREDENTIALS, SPREADSHEET_ID)
            months = []
            for r in list_months(client):
                if r.month == 0:
                    continue
                months.append({
                    "label": f"{r.title} {r.year}",
                    "ref": r,
                })
            self.after(0, lambda: self._on_connected(
                client, months))
        except Exception as exc:
            err_msg = str(exc)
            self.after(0, lambda: self._on_error(err_msg))

    def _on_connected(
            self, client: GoogleSheetsClient,
            months: list[dict]) -> None:
        self._client = client
        self._months_meta = months
        self._lb_months.delete(0, "end")
        for m in months:
            self._lb_months.insert("end", m["label"])
        self._btn_conn.configure(state="normal")
        self._btn_gen.configure(state="normal")
        self._lbl_status.configure(
            text=f"✓ {len(months)} вкладок",
            foreground="#28a745")
        self._log(
            f"Подключено: {len(months)} месячных вкладок")

    def _on_error(self, err: str) -> None:
        self._btn_conn.configure(state="normal")
        self._lbl_status.configure(
            text=f"✗ {err}", foreground="#dc3545")
        self._log(f"Ошибка подключения: {err}")

    # ======================================================== фильтры
    def _do_load_filters(self) -> None:
        sel = [int(i) for i in
               self._lb_months.curselection()]
        if not sel:
            self._log("Выберите хотя бы один месяц")
            return
        self._log("Загрузка данных…")
        threading.Thread(
            target=self._load_filters,
            args=(sel,), daemon=True).start()

    def _load_filters(
            self, indices: list[int]) -> None:
        try:
            refs = [
                self._months_meta[i]["ref"]
                for i in indices]
            grids = read_months(self._client, refs)
            uv = unique_values(grids)
            self.after(0, lambda: self._on_filters_loaded(
                uv, grids))
        except Exception as exc:
            err_msg = f"Ошибка загрузки: {exc}"
            self.after(0, lambda: self._log(err_msg))

    def _on_filters_loaded(
            self, uv: dict, grids) -> None:
        # Классы
        for w in self._frm_rooms.winfo_children():
            w.destroy()
        self._frm_rooms.columnconfigure(0, weight=1)
        self._room_vars.clear()
        row, col = 0, 0
        for room in uv["rooms"]:
            var = tk.BooleanVar(value=True)
            chk = ttk.Checkbutton(
                self._frm_rooms, text=room,
                variable=var)
            chk.grid(row=row, column=col, sticky="w",
                      padx=2, pady=1)
            self._room_vars[room] = var
            col += 1
            if col >= 2:
                col, row = 0, row + 1

        # Смены
        for w in self._frm_shifts.winfo_children():
            w.destroy()
        self._frm_shifts.columnconfigure(0, weight=1)
        self._shift_vars.clear()
        for shift in (MORNING, EVENING):
            var = tk.BooleanVar(value=True)
            chk = ttk.Checkbutton(
                self._frm_shifts, text=shift,
                variable=var)
            chk.grid(row=0 if shift == MORNING else 1,
                      column=0, sticky="w", padx=2, pady=1)
            self._shift_vars[shift] = var

        self._log(
            f"Фильтры: {len(uv['rooms'])} кл, "
            f"{len(uv['courses'])} курсов, "
            f"{len(uv['persons'])} лиц")

    # ========================================================= генерация
    def _do_generate(self) -> None:
        if not self._client:
            self._log("Сначала подключитесь к таблице")
            return
        if not self._lb_months.curselection():
            self._log("Выберите месяцы и загрузите фильтры")
            return
        threading.Thread(
            target=self._generate, daemon=True).start()

    def _generate(self) -> None:
        try:
            sel = [int(i) for i in
                   self._lb_months.curselection()]
            refs = [
                self._months_meta[i]["ref"]
                for i in sel]
            grids = read_months(self._client, refs)

            # фильтры
            rooms = tuple(r for r, v in
                          self._room_vars.items()
                          if v.get())
            shifts = tuple(
                s for s, v in self._shift_vars.items()
                if v.get())
            courses = tuple(
                c.strip() for c in self._entry_courses.get()
                .split(",") if c.strip())
            persons = tuple(
                p.strip() for p in self._entry_persons.get()
                .split(",") if p.strip())
            filt = Filters(
                rooms=rooms, shifts=shifts,
                courses=courses, persons=persons)

            simulate = self._mode_var.get() == "sim"
            intensity = float(
                self._sim_intensity.get())
            seed = self._sim_seed.get().strip() or ""
            author = (
                self._entry_author.get().strip()
                or "Завуч")
            approver = (
                self._entry_approver.get().strip()
                or "Зам. директора")

            self.after(
                0, lambda: self._log("Формирование…"))
            rep = build_report(
                grids, filters=filt,
                simulate=simulate,
                intensity=intensity,
                seed=seed,
                author=author,
                approver=approver)
            self.after(
                0, lambda: self._on_generated(rep))
        except Exception as exc:
            import traceback
            err_msg = f"Ошибка: {exc}\n{traceback.format_exc()}"
            self.after(0, lambda: self._log(err_msg))

    def _on_generated(
            self, report: dict) -> None:
        self._current_report = report
        self._show_preview(report)
        if report.get("error"):
            self._log(f"Ошибка: {report['error']}")
        else:
            mode = (
                "факт+сим"
                if report.get("simulated")
                else "факт")
            self._log(
                f"Готово: {report['occupied']} занятий, "
                f"{report['occupancy']:.1f}%, "
                f"режим={mode}")

    # ========================================================== выгрузка
    def _do_write(self) -> None:
        if (not self._current_report
                or not self._client):
            return
        threading.Thread(
            target=self._write, daemon=True).start()

    def _write(self) -> None:
        try:
            rep = self._current_report
            writer = ReportWriter(
                client=self._client)

            def progress(msg: str) -> None:
                self.after(
                    0,
                    lambda: self._log(msg))

            writer.write_report(
                rep, on_progress=progress)
            self.after(
                0,
                lambda: self._log(
                    "✓ Выгрузка завершена"))
        except Exception as exc:
            import traceback
            err_msg = f"Ошибка записи: {exc}\n{traceback.format_exc()}"
            self.after(0, lambda: self._log(err_msg))


# ================================================================ main
def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
