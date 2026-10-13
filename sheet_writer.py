"""
sheet_writer.py
===============

Выгрузка готового отчёта о занятости классов в Google-таблицу:
создание оформленной вкладки + запись строки в «Журнал отчётов».

Имя вкладки отражает домен и период: «Занятость. Окт–Ноя 2026».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from google_sheets_client import GoogleSheetsClient, GoogleSheetsError

# ------------------------------------------------------------------- config
def _load_config(path: str = "config.json") -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {"credentials_path": "", "spreadsheet_id": ""}


def _save_config(cfg: dict, path: str = "config.json") -> None:
    Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=4),
                          encoding="utf-8")


# ------------------------------------------------------------------- helpers
def _sanitize_title(text: str, maxlen: int = 31) -> str:
    """Имя вкладки: ≤ 31 символа, без []:*?/\\ ."""
    bad = "[]:*?/\\"
    return "".join(c if c not in bad else "_" for c in text[:maxlen])


def _unique_title(client: GoogleSheetsClient, title: str) -> str:
    existing = set(client.sheet_titles())
    if title not in existing:
        return title
    base = title[:24]
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


def _tab_name(report: dict[str, Any]) -> str:
    """«Занятость. Окт–Ноя 2026» по списку месяцев отчёта."""
    months = report.get("months") or []
    years = sorted({m.split()[-1] for m in months if m.split()})
    year = years[0] if years else ""
    if not months:
        return _sanitize_title(f"Занятость {year}")
    shorts = [m.split()[0][:3] for m in months]
    span = "–".join([shorts[0], shorts[-1]]) if len(shorts) > 1 else shorts[0]
    return _sanitize_title(f"Занятость. {span} {year}".strip())


# ------------------------------------------------------- main writer class
class ReportWriter:
    """Пишет оформленные отчёты в Google-таблицу и ведёт журнал."""

    LOG_TAB = "Журнал отчётов"
    LOG_HEADERS = [
        "Дата формирования", "Период", "Месяцы", "Классов",
        "Фонд слотов", "Проведено занятий", "Занятость, %",
        "Режим", "Составил", "Ссылка",
    ]

    def __init__(
        self,
        credentials_path: str | None = None,
        spreadsheet_id: str = "",
        client: GoogleSheetsClient | None = None,
    ):
        cfg = _load_config()
        cred = credentials_path or cfg.get("credentials_path", "")
        sid = spreadsheet_id or cfg.get("spreadsheet_id", "")
        if client is not None:
            self._client = client
            sid = sid or client.spreadsheet_id
        else:
            self._client = GoogleSheetsClient(cred, sid or None)
        self._credentials_path = cred
        self._spreadsheet_id = sid
        self._new_spreadsheet: str | None = None
        self._owns_client = client is None

    @property
    def spreadsheet_id(self) -> str:
        return self._spreadsheet_id or self._new_spreadsheet or ""

    @property
    def spreadsheet_url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"

    @property
    def client(self) -> GoogleSheetsClient:
        return self._client

    def setup_spreadsheet(self) -> str:
        if self.spreadsheet_id:
            return self.spreadsheet_id
        try:
            available = GoogleSheetsClient.list_spreadsheets(
                self._credentials_path)
        except GoogleSheetsError:
            available = []
        if not available:
            raise GoogleSheetsError(
                "В config.json не указан spreadsheet_id.\n"
                "Скопируйте id из адреса "
                "https://docs.google.com/spreadsheets/d/<ID>/edit\n"
                f"Поделитесь таблицей с аккаунтом "
                f"{self._client.service_account_email} (редактор).")
        self._new_spreadsheet = available[0]["id"]
        self._client._spreadsheet_id = self._new_spreadsheet  # noqa: SLF001
        cfg = _load_config()
        cfg["spreadsheet_id"] = self._new_spreadsheet
        _save_config(cfg)
        return self._new_spreadsheet

    # ---- журнал --------------------------------------------------------- #
    def _ensure_log_tab(self) -> None:
        titles = self._client.sheet_titles()
        if self.LOG_TAB not in titles:
            self._client.create_sheet(
                self.LOG_TAB,
                grid_rows=1000, grid_columns=len(self.LOG_HEADERS) + 2)
        self._client.use_sheet(self.LOG_TAB)
        if self._client.count_rows() == 0:
            self._client.write("A1", [self.LOG_HEADERS])

    def _style_log_tab(self) -> None:
        client = self._client
        sid = client.sheet_id(self.LOG_TAB)
        n = len(self.LOG_HEADERS)
        hr = {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
              "startColumnIndex": 0, "endColumnIndex": n}
        client._execute(  # noqa: SLF001
            client.service.spreadsheets().batchUpdate(
                spreadsheetId=client.spreadsheet_id,
                body={"requests": [
                    {"repeatCell": {"range": hr, "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True, "fontSize": 10,
                                           "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            "backgroundColor": {"red": 0.184, "green": 0.333, "blue": 0.592},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                        }},
                        "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment,verticalAlignment)",
                    }},
                    {"updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "COLUMNS",
                                  "startIndex": 0, "endIndex": n},
                        "properties": {"pixelSize": 140},
                        "fields": "pixelSize",
                    }},
                    {"updateSheetProperties": {
                        "properties": {"sheetId": sid,
                                       "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }},
                ]},
            )
        )

    def _append_log(self, report: dict[str, Any], sheet_id: int) -> None:
        self._ensure_log_tab()
        period = (f"{report['period_from'].strftime('%d.%m.%Y')} — "
                  f"{report['period_to'].strftime('%d.%m.%Y')}")
        url = f"{self.spreadsheet_url}/edit#gid={sheet_id}"
        link = f'=HYPERLINK("{url}";"Открыть отчёт")'
        mode = "факт + симуляция" if report.get("simulated") else "только факт"
        self._client.append_row([
            report["generated_at"].strftime("%d.%m.%Y %H:%M"),
            period,
            ", ".join(report.get("months", [])),
            len(report.get("rooms", [])),
            report["capacity"],
            report["occupied"],
            round(report["occupancy"], 1),
            mode,
            report.get("author", ""),
            link,
        ])
        self._style_log_tab()

    # ---- выгрузка отчёта ------------------------------------------------ #
    def write_report(
        self,
        report: dict[str, Any],
        on_progress: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        """Отрисовать отчёт в новой вкладке, вернуть её координаты."""
        from document_builder import ReportDocument
        from report_layout import render_report

        client = self._client

        def say(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        if report.get("error"):
            raise ValueError(report["error"])

        # 1. измерение (без реального sheet_id)
        say("Измерение документа…")
        probe = ReportDocument(0)
        render_report(probe, report)
        rows_needed = probe.build().rows

        # 2. создание вкладки
        title = _unique_title(client, _tab_name(report))
        say(f"Создание вкладки «{title}»…")
        client.create_sheet(title, grid_rows=rows_needed + 15, grid_columns=10)
        client.use_sheet(title)
        sheet_id = client.sheet_id(title)

        # 3. второй проход с реальным sheet_id
        say("Построение документа…")
        doc = ReportDocument(sheet_id)
        render_report(doc, report)
        spec = doc.build()

        say("Запись значений…")
        client.write(f"A1:I{spec.rows}", spec.values)

        say("Применение оформления…")
        chunk, requests = 80, spec.requests
        for i in range(0, len(requests), chunk):
            body = {"requests": requests[i: i + chunk]}
            try:
                client._execute(  # noqa: SLF001
                    client.service.spreadsheets().batchUpdate(
                        spreadsheetId=client.spreadsheet_id, body=body)
                )
            except GoogleSheetsError as exc:
                say(f"⚠ Часть оформления: {exc}")

        say("Журнал…")
        self._append_log(report, sheet_id)
        say(f"✓ «{title}»")
        return {"title": title, "sheet_id": sheet_id,
                "url": self.report_url(sheet_id)}

    def report_url(self, sheet_id: int) -> str:
        return f"{self.spreadsheet_url}/edit#gid={sheet_id}"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ReportWriter":
        self.setup_spreadsheet()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
