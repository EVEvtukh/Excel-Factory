"""
crm_app.py
==========

Tkinter-интерфейс CRM. Общается с FastAPI-бэкендом на localhost:8000.
Запуск:  python crm_app.py
"""
from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# Подключаем директорию sheets для импорта Google-модулей
_GOOGLE_DIR = Path(__file__).resolve().parent.parent / "sheets"
if str(_GOOGLE_DIR) not in sys.path:
    sys.path.insert(0, str(_GOOGLE_DIR))

API = "http://127.0.0.1:8000"


# =====================================================================
#  HTTP-хелперы
# =====================================================================

def api(method: str, path: str, body: dict | None = None) -> dict | list:
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {err}")


# =====================================================================
#  Диалог создания/редактирования клиента
# =====================================================================

class ClientDialog(tk.Toplevel):
    def __init__(self, parent, client: dict | None = None):
        super().__init__(parent)
        self.title("Редактировать клиента" if client else "Новый клиент")
        self.geometry("400x380")
        self.resizable(False, False)
        self.result: dict | None = None
        self._client = client or {}
        self._build()

    def _build(self):
        c = self._client
        pad = {"padx": 10, "pady": 4}
        fields = [
            ("Имя", "first_name", c.get("first_name", "")),
            ("Фамилия", "last_name", c.get("last_name", "")),
            ("Телефон", "phone", c.get("phone", "")),
            ("Email", "email", c.get("email", "")),
        ]
        for i, (label, key, val) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", **pad)
            e = ttk.Entry(self, width=35)
            e.insert(0, val)
            e.grid(row=i, column=1, **pad)
            setattr(self, f"e_{key}", e)
        ttk.Label(self, text="Заметки").grid(row=4, column=0, sticky="w", **pad)
        self.e_notes = tk.Text(self, width=35, height=4)
        self.e_notes.insert("1.0", c.get("notes", ""))
        self.e_notes.grid(row=4, column=1, **pad)
        btns = ttk.Frame(self)
        btns.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

    def _save(self):
        self.result = {
            "first_name": self.e_first_name.get().strip(),
            "last_name": self.e_last_name.get().strip(),
            "phone": self.e_phone.get().strip(),
            "email": self.e_email.get().strip(),
            "notes": self.e_notes.get("1.0", "end").strip(),
        }
        if not self.result["first_name"]:
            messagebox.showwarning("Внимание", "Укажите имя клиента", parent=self)
            return
        self.destroy()


# =====================================================================
#  Диалог создания/редактирования сделки
# =====================================================================

class DealDialog(tk.Toplevel):
    def __init__(self, parent, deal: dict | None = None, clients: list | None = None):
        super().__init__(parent)
        self.title("Редактировать сделку" if deal else "Новая сделка")
        self.geometry("440x420")
        self.resizable(False, False)
        self.result: dict | None = None
        self._deal = deal or {}
        self._clients = clients or []
        self._build()

    def _build(self):
        d = self._deal
        pad = {"padx": 10, "pady": 4}
        ttk.Label(self, text="Клиент").grid(row=0, column=0, sticky="w", **pad)
        names = ["— без клиента —"] + [
            f"{c['id']} | {c['first_name']} {c['last_name']}".strip()
            for c in self._clients
        ]
        self.cb_client = ttk.Combobox(self, values=names, state="readonly", width=32)
        if d.get("client_id"):
            for i, c in enumerate(self._clients):
                if c["id"] == d["client_id"]:
                    self.cb_client.current(i + 1)
                    break
        else:
            self.cb_client.current(0)
        self.cb_client.grid(row=0, column=1, **pad)
        fields = [
            ("Название", "title", d.get("title", "")),
            ("Статус", "status", d.get("status", "new")),
            ("Сумма", "amount", str(d.get("amount", 0))),
        ]
        for i, (label, key, val) in enumerate(fields, start=1):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", **pad)
            e = ttk.Entry(self, width=35)
            e.insert(0, val)
            e.grid(row=i, column=1, **pad)
            setattr(self, f"e_{key}", e)
        ttk.Label(self, text="Описание").grid(row=4, column=0, sticky="w", **pad)
        self.e_desc = tk.Text(self, width=35, height=4)
        self.e_desc.insert("1.0", d.get("description", ""))
        self.e_desc.grid(row=4, column=1, **pad)
        btns = ttk.Frame(self)
        btns.grid(row=5, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

    def _save(self):
        idx = self.cb_client.current()
        client_id = self._clients[idx - 1]["id"] if idx > 0 else None
        try:
            amount = float(self.e_amount.get())
        except ValueError:
            amount = 0.0
        self.result = {
            "client_id": client_id,
            "title": self.e_title.get().strip(),
            "description": self.e_desc.get("1.0", "end").strip(),
            "status": self.e_status.get().strip(),
            "amount": amount,
        }
        if not self.result["title"]:
            messagebox.showwarning("Внимание", "Укажите название сделки", parent=self)
            return
        self.destroy()


# =====================================================================
#  Диалог создания/редактирования задачи
# =====================================================================

class TaskDialog(tk.Toplevel):
    def __init__(self, parent, task: dict | None = None,
                 clients: list | None = None, deals: list | None = None):
        super().__init__(parent)
        self.title("Редактировать задачу" if task else "Новая задача")
        self.geometry("460x460")
        self.resizable(False, False)
        self.result: dict | None = None
        self._task = task or {}
        self._clients = clients or []
        self._deals = deals or []
        self._build()

    def _build(self):
        t = self._task
        pad = {"padx": 10, "pady": 4}
        ttk.Label(self, text="Клиент").grid(row=0, column=0, sticky="w", **pad)
        cn = ["— без клиента —"] + [
            f"{c['id']} | {c['first_name']} {c['last_name']}".strip()
            for c in self._clients
        ]
        self.cb_client = ttk.Combobox(self, values=cn, state="readonly", width=32)
        if t.get("client_id"):
            for i, c in enumerate(self._clients):
                if c["id"] == t["client_id"]:
                    self.cb_client.current(i + 1)
                    break
        else:
            self.cb_client.current(0)
        self.cb_client.grid(row=0, column=1, **pad)
        ttk.Label(self, text="Сделка").grid(row=1, column=0, sticky="w", **pad)
        dn = ["— без сделки —"] + [
            f"{d['id']} | {d['title']}" for d in self._deals
        ]
        self.cb_deal = ttk.Combobox(self, values=dn, state="readonly", width=32)
        if t.get("deal_id"):
            for i, d in enumerate(self._deals):
                if d["id"] == t["deal_id"]:
                    self.cb_deal.current(i + 1)
                    break
        else:
            self.cb_deal.current(0)
        self.cb_deal.grid(row=1, column=1, **pad)
        fields = [
            ("Название", "title", t.get("title", "")),
            ("Статус", "status", t.get("status", "pending")),
            ("Приоритет", "priority", t.get("priority", "normal")),
            ("Дедлайн", "due_date", t.get("due_date", "")),
        ]
        for i, (label, key, val) in enumerate(fields, start=2):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", **pad)
            e = ttk.Entry(self, width=35)
            e.insert(0, val)
            e.grid(row=i, column=1, **pad)
            setattr(self, f"e_{key}", e)
        ttk.Label(self, text="Описание").grid(row=6, column=0, sticky="w", **pad)
        self.e_desc = tk.Text(self, width=35, height=3)
        self.e_desc.insert("1.0", t.get("description", ""))
        self.e_desc.grid(row=6, column=1, **pad)
        btns = ttk.Frame(self)
        btns.grid(row=7, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left", padx=6)
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

    def _save(self):
        ci = self.cb_client.current()
        di = self.cb_deal.current()
        self.result = {
            "client_id": self._clients[ci - 1]["id"] if ci > 0 else None,
            "deal_id": self._deals[di - 1]["id"] if di > 0 else None,
            "title": self.e_title.get().strip(),
            "description": self.e_desc.get("1.0", "end").strip(),
            "status": self.e_status.get().strip(),
            "priority": self.e_priority.get().strip(),
            "due_date": self.e_due_date.get().strip(),
        }
        if not self.result["title"]:
            messagebox.showwarning("Внимание", "Укажите название задачи", parent=self)
            return
        self.destroy()


# =====================================================================
#  Настройки Google
# =====================================================================

class GoogleSettingsDialog(tk.Toplevel):
    """Окно настроек Google OAuth + папка."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Настройки Google")
        self.result: dict | None = None
        self._settings = self._load_settings()
        self._build()

    @staticmethod
    def _load_settings() -> dict:
        try:
            from crm_google_settings import load_settings
            return load_settings()
        except Exception:
            return {}

    def _build(self):
        # Кнопки всегда прижаты к низу — видны при любом размере окна
        btns = ttk.Frame(self)
        btns.pack(side="bottom", fill="x", pady=14)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left", padx=(20, 6))
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="left", padx=6)

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(10, 0))
        body.columnconfigure(1, weight=1)
        pad = {"pady": 6}
        ipady = {"ipady": 4}

        ttk.Label(body, text="Client Secret (JSON)").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        frame_cs = ttk.Frame(body)
        frame_cs.grid(row=0, column=1, sticky="we", **pad)
        frame_cs.columnconfigure(0, weight=1)
        self.e_cs = ttk.Entry(frame_cs, width=40)
        self.e_cs.grid(row=0, column=0, sticky="we", **ipady)
        ttk.Button(frame_cs, text="Обзор...", command=self._browse_cs).grid(row=0, column=1, padx=(6, 0), sticky="e")

        ttk.Label(body, text="Folder ID (папка на Drive)").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        frame_fid = ttk.Frame(body)
        frame_fid.grid(row=1, column=1, sticky="we", **pad)
        frame_fid.columnconfigure(0, weight=1)
        self.e_fid = ttk.Entry(frame_fid, width=40)
        self.e_fid.grid(row=0, column=0, sticky="we", **ipady)
        ttk.Button(frame_fid, text="Вставить", command=self._paste_fid).grid(row=0, column=1, padx=(6, 0), sticky="e")

        info_text = (
            "Как получить Client Secret:\n"
            "  1) console.cloud.google.com → API & Services → Credentials\n"
            "  2) Create → OAuth Client ID → Desktop app\n"
            "  3) Download JSON\n"
            "\n"
            "Folder ID — из URL папки Drive:\n"
            "  https://drive.google.com/drive/folders/<ID>\n"
            "Оставьте пустым для корня Drive."
        )
        info_lbl = tk.Text(body, width=58, height=8, font=("Consolas", 8), relief="sunken", padx=6, pady=4)
        info_lbl.grid(row=2, column=0, columnspan=2, sticky="nsew", **pad)
        info_lbl.insert("1.0", info_text)
        info_lbl.config(state="disabled")
        body.grid_rowconfigure(2, weight=1)

        # Стартовый размер окна (можно растягивать, если что-то обрезалось)
        self.geometry("560x400")
        self.minsize(480, 320)
        self.resizable(True, True)

    def _browse_cs(self):
        path = filedialog.askopenfilename(
            title="Выберите client_secret JSON",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if path:
            self.e_cs.delete(0, "end")
            self.e_cs.insert(0, path)

    def _paste_fid(self):
        try:
            pasted = self.clipboard_get()
            if pasted:
                self.e_fid.delete(0, "end")
                self.e_fid.insert(0, pasted.strip())
        except tk.TclError:
            pass

    def _save(self):
        self.result = {
            "google_client_secret_path": self.e_cs.get().strip(),
            "google_folder_id": self.e_fid.get().strip(),
        }
        try:
            from crm_google_settings import save_settings
            save_settings(self.result)
        except Exception:
            pass
        self.destroy()


# =====================================================================
#  Прогресс-окно экспорта
# =====================================================================

class ExportProgressDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Экспорт в Google Sheets")
        self.geometry("500x200")
        self.resizable(False, False)
        self._cancel = False
        self._build()

    def _build(self):
        ttk.Label(self, text="Создаётся отчёт...").pack(pady=(16, 4))
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=400)
        self.progress.pack(pady=4)
        self.progress.start(10)
        self.lbl_status = ttk.Label(self, text="", foreground="gray")
        self.lbl_status.pack(pady=2)
        self.btn_open = ttk.Button(self, text="Открыть в браузере", state="disabled", command=self._open_url)
        self.btn_open.pack(pady=4)
        self.btn_close = ttk.Button(self, text="Закрыть", state="disabled", command=self.destroy)
        self.btn_close.pack(pady=4)
        self._url = ""

    def set_status(self, text: str):
        self.lbl_status.config(text=text)
        self.update()

    def _open_url(self):
        if self._url:
            import webbrowser
            webbrowser.open(self._url)

    def _cancel_export(self):
        self._cancel = True

    def done(self, success: bool, message: str, url: str = ""):
        self.progress.stop()
        self.btn_close.config(state="normal")
        color = "green" if success else "red"
        self.lbl_status.config(text=message, foreground=color)
        if success and url:
            self._url = url
            self.btn_open.config(state="normal")
            self.lbl_status.config(text=message + f"\n{url}")


# =====================================================================
#  Экспорт данных
# =====================================================================

def _export_tab_data(tab, tab_name: str):
    """Выгрузить данные вкладки в Google Sheets."""
    try:
        from google_drive_user_client import GoogleDriveUserClient
        from google_sheets_user_client import GoogleSheetsUserClient
        from google_sheets_client import col_number_to_letter
    except ImportError as e:
        messagebox.showerror("Ошибка", f"Модули Google не найдены:\n{e}")
        return

    # Загрузить настройки
    try:
        from crm_google_settings import load_settings
        settings = load_settings()
    except Exception:
        settings = {}

    if not settings.get("google_client_secret_path"):
        # Настроек нет — открыть окно и дождаться, пока пользователь сохранит
        dlg = GoogleSettingsDialog(tab.winfo_toplevel())
        tab.wait_window(dlg)
        try:
            from crm_google_settings import load_settings
            settings = load_settings()
        except Exception:
            settings = {}

    if not settings.get("google_client_secret_path"):
        messagebox.showwarning("Настройки", "Укажите Client Secret в настройках Google.")
        return

    prog = ExportProgressDialog(tab)
    prog.grab_set()

    def _do_export():
        try:
            client_secret = settings["google_client_secret_path"]
            folder_id = settings.get("google_folder_id", "")

            prog.set_status("Авторизация Google...")

            title = f"CRM Отчёт — {tab_name} — {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"

            drive = GoogleDriveUserClient(client_secret_path=client_secret)
            if folder_id:
                drive_meta = drive.create_spreadsheet(title, parent_folder_id=folder_id)
            else:
                drive_meta = drive.create_spreadsheet(title)
            spreadsheet_id = drive_meta["id"]
            drive.close()

            prog.set_status("Подготовка данных...")

            tree = tab.tree
            columns = list(tab.COLUMNS)
            headers = tab.HEADERS
            data_rows: list[list] = [list(headers)]

            for item in tree.get_children():
                vals = tree.item(item, "values")
                data_rows.append(list(vals))

            prog.set_status("Запись данных в Google Sheets...")
            with GoogleSheetsUserClient(
                client_secret_path=client_secret,
                spreadsheet_id=spreadsheet_id,
            ) as sheets:
                sheets.write("A1", data_rows)

                last_col = len(headers)
                last_row = len(data_rows)
                header_range = f"A1:{col_number_to_letter(last_col)}1"
                sheets.format_range(
                    header_range,
                    bold=True,
                    background_color=(0.25, 0.55, 0.95, 1.0),
                    text_color=(1.0, 1.0, 1.0, 1.0),
                    horizontal_alignment="CENTER",
                )

                if last_row > 1:
                    data_range = f"A2:{col_number_to_letter(last_col)}{last_row}"
                    sheets.format_range(data_range, wrap_strategy="WRAP_STRING")

                prog.set_status("Настройка ширины столбцов...")
                for col_idx in range(1, last_col + 1):
                    col_letter = col_number_to_letter(col_idx)
                    try:
                        sheets.set_column_width(f"{col_letter}1:{col_letter}{last_row}", 150)
                    except Exception:
                        pass

                prog.set_status("Закрепление заголовков...")
                try:
                    sheets.freeze_panes(row_count=1)
                except Exception:
                    pass

            prog.set_status("Готово!")
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            prog.done(True, "Таблица создана!", url=sheet_url)
            prog.deiconify()

        except Exception as e:
            prog.set_status(f"Ошибка: {e}")
            prog.done(False, str(e))

    threading.Thread(target=_do_export, daemon=True).start()


# =====================================================================
#  Вкладки с таблицами
# =====================================================================

class ClientsTab(ttk.Frame):
    COLUMNS = ("id", "first_name", "last_name", "phone", "email", "status", "notes")
    HEADERS = ("ID", "Имя", "Фамилия", "Телефон", "Email", "Статус", "Заметки")
    WIDTHS = (40, 110, 110, 130, 170, 80, 200)

    def __init__(self, master):
        super().__init__(master)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(top, text="Поиск:").pack(side="left", padx=(0, 4))
        self.e_search = ttk.Entry(top, width=25)
        self.e_search.pack(side="left", padx=(0, 6))
        self.e_search.bind("<Return>", lambda e: self.refresh())
        ttk.Label(top, text="Статус:").pack(side="left", padx=(0, 4))
        self.cb_status = ttk.Combobox(top, values=["все", "active", "archived"], state="readonly", width=10)
        self.cb_status.current(0)
        self.cb_status.pack(side="left", padx=(0, 10))
        ttk.Button(top, text="Найти", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Обновить", command=self._clear_and_refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Добавить", command=self._add).pack(side="right", padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(mid, columns=self.COLUMNS, show="headings", height=18)
        for col, hdr, w in zip(self.COLUMNS, self.HEADERS, self.WIDTHS):
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w, minwidth=35)
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        # нижняя панель
        bot = ttk.Frame(self)
        bot.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(bot, text="Редактировать", command=self._edit).pack(side="left", padx=2)
        ttk.Button(bot, text="Архивировать", command=self._archive).pack(side="left", padx=2)
        ttk.Button(bot, text="Удалить", command=self._delete).pack(side="left", padx=2)
        ttk.Separator(bot, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bot, text="📊 Выгрузить отчёт", command=self._export).pack(side="right", padx=2)

    def _export(self):
        _export_tab_data(self, "Клиенты")

    def _get_selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    def refresh(self):
        search = self.e_search.get().strip() or None
        status_val = self.cb_status.get()
        status = None if status_val == "все" else status_val
        params = []
        if search:
            params.append(f"search={search}")
        if status:
            params.append(f"status={status}")
        path = "/clients"
        if params:
            path += "?" + "&".join(params)
        try:
            data = api("GET", path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить клиентов:\n{e}")
            return
        self.tree.delete(*self.tree.get_children())
        for c in data:
            self.tree.insert("", "end", values=(
                c["id"], c["first_name"], c["last_name"],
                c["phone"], c["email"], c["status"], c["notes"][:60],
            ))

    def _clear_and_refresh(self):
        self.e_search.delete(0, "end")
        self.cb_status.current(0)
        self.refresh()

    def _add(self):
        dlg = ClientDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("POST", "/clients", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _edit(self):
        cid = self._get_selected_id()
        if cid is None:
            return
        try:
            client = api("GET", f"/clients/{cid}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        dlg = ClientDialog(self, client)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("PATCH", f"/clients/{cid}", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _archive(self):
        cid = self._get_selected_id()
        if cid is None:
            return
        if not messagebox.askyesno("Архивировать", f"Архивировать клиента #{cid}?"):
            return
        try:
            api("POST", f"/clients/{cid}/archive")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh()

    def _delete(self):
        cid = self._get_selected_id()
        if cid is None:
            return
        if not messagebox.askyesno("Удалить", f"Удалить клиента #{cid}?"):
            return
        try:
            api("DELETE", f"/clients/{cid}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh()


# ----------------------------------------------------------------- Deals

class DealsTab(ttk.Frame):
    COLUMNS = ("id", "client_id", "title", "status", "amount", "description")
    HEADERS = ("ID", "Клиент", "Название", "Статус", "Сумма", "Описание")
    WIDTHS = (40, 70, 180, 100, 90, 250)

    def __init__(self, master):
        super().__init__(master)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(top, text="Поиск:").pack(side="left", padx=(0, 4))
        self.e_search = ttk.Entry(top, width=25)
        self.e_search.pack(side="left", padx=(0, 6))
        self.e_search.bind("<Return>", lambda e: self.refresh())
        ttk.Label(top, text="Статус:").pack(side="left", padx=(0, 4))
        self.cb_status = ttk.Combobox(top, values=["все", "new", "in_progress", "closed", "cancelled"], state="readonly", width=12)
        self.cb_status.current(0)
        self.cb_status.pack(side="left", padx=(0, 10))
        ttk.Button(top, text="Найти", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Обновить", command=self._clear_and_refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Добавить", command=self._add).pack(side="right", padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(mid, columns=self.COLUMNS, show="headings", height=18)
        for col, hdr, w in zip(self.COLUMNS, self.HEADERS, self.WIDTHS):
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w, minwidth=35)
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        # нижняя панель
        bot = ttk.Frame(self)
        bot.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(bot, text="Редактировать", command=self._edit).pack(side="left", padx=2)
        ttk.Button(bot, text="Удалить", command=self._delete).pack(side="left", padx=2)
        ttk.Separator(bot, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bot, text="📊 Выгрузить отчёт", command=self._export).pack(side="right", padx=2)

    def _export(self):
        _export_tab_data(self, "Сделки")

    def _get_selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    def refresh(self):
        search = self.e_search.get().strip() or None
        status_val = self.cb_status.get()
        status = None if status_val == "все" else status_val
        params = []
        if search:
            params.append(f"search={search}")
        if status:
            params.append(f"status={status}")
        path = "/deals"
        if params:
            path += "?" + "&".join(params)
        try:
            data = api("GET", path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить сделки:\n{e}")
            return
        self.tree.delete(*self.tree.get_children())
        for d in data:
            self.tree.insert("", "end", values=(
                d["id"], d["client_id"] or "—", d["title"],
                d["status"], f"{d['amount']:,.0f}", d["description"][:60],
            ))

    def _clear_and_refresh(self):
        self.e_search.delete(0, "end")
        self.cb_status.current(0)
        self.refresh()

    def _add(self):
        clients = self._fetch_clients()
        dlg = DealDialog(self, clients=clients)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("POST", "/deals", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _edit(self):
        did = self._get_selected_id()
        if did is None:
            return
        try:
            deal = api("GET", f"/deals/{did}")
            clients = self._fetch_clients()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        dlg = DealDialog(self, deal, clients)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("PATCH", f"/deals/{did}", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _delete(self):
        did = self._get_selected_id()
        if did is None:
            return
        if not messagebox.askyesno("Удалить", f"Удалить сделку #{did}?"):
            return
        try:
            api("DELETE", f"/deals/{did}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh()

    @staticmethod
    def _fetch_clients() -> list:
        try:
            return api("GET", "/clients?limit=500")
        except Exception:
            return []


# ----------------------------------------------------------------- Tasks

class TasksTab(ttk.Frame):
    COLUMNS = ("id", "client_id", "deal_id", "title", "status", "priority", "due_date", "description")
    HEADERS = ("ID", "Клиент", "Сделка", "Название", "Статус", "Приоритет", "Дедлайн", "Описание")
    WIDTHS = (40, 60, 60, 160, 90, 70, 90, 180)

    def __init__(self, master):
        super().__init__(master)
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Label(top, text="Поиск:").pack(side="left", padx=(0, 4))
        self.e_search = ttk.Entry(top, width=25)
        self.e_search.pack(side="left", padx=(0, 6))
        self.e_search.bind("<Return>", lambda e: self.refresh())
        ttk.Label(top, text="Статус:").pack(side="left", padx=(0, 4))
        self.cb_status = ttk.Combobox(top, values=["все", "pending", "in_progress", "completed"], state="readonly", width=12)
        self.cb_status.current(0)
        self.cb_status.pack(side="left", padx=(0, 10))
        ttk.Button(top, text="Найти", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Обновить", command=self._clear_and_refresh).pack(side="left", padx=2)
        ttk.Button(top, text="Добавить", command=self._add).pack(side="right", padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(mid, columns=self.COLUMNS, show="headings", height=18)
        for col, hdr, w in zip(self.COLUMNS, self.HEADERS, self.WIDTHS):
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w, minwidth=35)
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        # нижняя панель
        bot = ttk.Frame(self)
        bot.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(bot, text="Редактировать", command=self._edit).pack(side="left", padx=2)
        ttk.Button(bot, text="Выполнить", command=self._complete).pack(side="left", padx=2)
        ttk.Button(bot, text="Удалить", command=self._delete).pack(side="left", padx=2)
        ttk.Separator(bot, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bot, text="📊 Выгрузить отчёт", command=self._export).pack(side="right", padx=2)

    def _export(self):
        _export_tab_data(self, "Задачи")

    def _get_selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return int(vals[0])

    def refresh(self):
        search = self.e_search.get().strip() or None
        status_val = self.cb_status.get()
        status = None if status_val == "все" else status_val
        params = []
        if search:
            params.append(f"search={search}")
        if status:
            params.append(f"status={status}")
        path = "/tasks"
        if params:
            path += "?" + "&".join(params)
        try:
            data = api("GET", path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить задачи:\n{e}")
            return
        self.tree.delete(*self.tree.get_children())
        for t in data:
            self.tree.insert("", "end", values=(
                t["id"], t["client_id"] or "—", t["deal_id"] or "—",
                t["title"], t["status"], t["priority"], t["due_date"] or "—",
                t["description"][:60],
            ))

    def _clear_and_refresh(self):
        self.e_search.delete(0, "end")
        self.cb_status.current(0)
        self.refresh()

    def _add(self):
        clients = self._fetch_clients()
        deals = self._fetch_deals()
        dlg = TaskDialog(self, clients=clients, deals=deals)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("POST", "/tasks", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _edit(self):
        tid = self._get_selected_id()
        if tid is None:
            return
        try:
            task = api("GET", f"/tasks/{tid}")
            clients = self._fetch_clients()
            deals = self._fetch_deals()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        dlg = TaskDialog(self, task, clients, deals)
        self.wait_window(dlg)
        if dlg.result:
            try:
                api("PATCH", f"/tasks/{tid}", dlg.result)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
                return
            self.refresh()

    def _complete(self):
        tid = self._get_selected_id()
        if tid is None:
            return
        try:
            api("POST", f"/tasks/{tid}/complete")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh()

    def _delete(self):
        tid = self._get_selected_id()
        if tid is None:
            return
        if not messagebox.askyesno("Удалить", f"Удалить задачу #{tid}?"):
            return
        try:
            api("DELETE", f"/tasks/{tid}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh()

    @staticmethod
    def _fetch_clients() -> list:
        try:
            return api("GET", "/clients?limit=500")
        except Exception:
            return []

    @staticmethod
    def _fetch_deals() -> list:
        try:
            return api("GET", "/deals?limit=500")
        except Exception:
            return []


# =====================================================================
#  Главное окно
# =====================================================================

class CRMApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mini CRM")
        self.geometry("1100x650")
        self.minsize(900, 500)
        self._build()

    def _build(self):
        # Меню настроек
        menubar = tk.Menu(self)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Настройки Google...", command=self._open_google_settings)
        settings_menu.add_separator()
        settings_menu.add_command(label="Выход", command=self.quit)
        menubar.add_cascade(label="Файл", menu=settings_menu)
        self.config(menu=menubar)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        self.tab_clients = ClientsTab(nb)
        self.tab_deals = DealsTab(nb)
        self.tab_tasks = TasksTab(nb)

        nb.add(self.tab_clients, text="  Клиенты  ")
        nb.add(self.tab_deals, text="  Сделки  ")
        nb.add(self.tab_tasks, text="  Задачи  ")

        # статус-бар
        status_bar = ttk.Frame(self)
        status_bar.pack(fill="x", side="bottom")
        status = ttk.Label(status_bar, text="API: http://127.0.0.1:8000",
                           relief="sunken", anchor="w", padding=(4, 2))
        status.pack(side="left", fill="x", expand=True)
        ttk.Button(status_bar, text="⚙ Google", command=self._open_google_settings).pack(side="right", padx=2, pady=1)

    def _open_google_settings(self):
        dlg = GoogleSettingsDialog(self)
        dlg.grab_set()


# =====================================================================
#  Entry point
# =====================================================================

if __name__ == "__main__":
    app = CRMApp()
    app.mainloop()
