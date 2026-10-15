"""
google_sheets_user_client.py
============================

OAuth2-клиент для Google Sheets API v4 (аутентификация пользователя).

Позволяет работать с таблицами от имени авторизованного пользователя.
Первый запуск открывает браузер для согласия, токен кэшируется в token_sheets.json.

    from google_sheets_user_client import GoogleSheetsUserClient

    with GoogleSheetsUserClient() as sheets:
        rows = sheets.read_all()
        sheets.write("A1:C3", [["x", "y", "z"]])
        sheets.format_range("A1:C1", bold=True, background_color=(0.2, 0.6, 1.0, 1.0))

Зависимости (помимо google_sheets_client.py):
    google-auth-oauthlib
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from google_sheets_client import (
    GoogleSheetsClient,
    GoogleSheetsError,
    _to_2d,
)
from googleapiclient.discovery import build

__all__ = ["GoogleSheetsUserClient", "SheetsAuthError"]

DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class SheetsAuthError(GoogleSheetsError):
    pass


_ACCESS_DENIED_HINT = (
    "Google вернул 'access_denied'. OAuth-приложение в режиме тестирования.\n\n"
    "Исправление:\n"
    "  1) https://console.cloud.google.com/apis/credentials/consent\n"
    "  2) 'Audience' → 'External', Save\n"
    "  3) 'Test users' → добавить ваш аккаунт\n"
    "  4) Save, повторить.\n"
)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class GoogleSheetsUserClient(GoogleSheetsClient):
    """Sheets API от имени пользователя через OAuth2."""

    def __init__(
        self,
        client_secret_path: str | os.PathLike[str] | None = None,
        token_path: str | os.PathLike[str] | None = None,
        spreadsheet_id: str = "",
        sheet_name: str | None = None,
        *,
        scopes: Sequence[str] = DEFAULT_SCOPES,
        value_input_option: str = "USER_ENTERED",
    ) -> None:
        # НЕ вызываем super().__init__(): базовый GoogleSheetsClient при
        # инициализации ищет service-account JSON, который OAuth2-клиенту
        # не нужен. Инициализируем нужные атрибуты напрямую.
        self._spreadsheet_id = GoogleSheetsClient.parse_spreadsheet_id(spreadsheet_id)
        self._sheet_name = sheet_name or None
        self._value_input_option = value_input_option
        self._credentials = None  # не используется, переопределено property ниже
        self._service = None

        self._client_secret_path = self._resolve_client_secret_path(client_secret_path)
        self._token_path = (
            Path(token_path).expanduser().resolve()
            if token_path
            else Path(__file__).resolve().parent / "token_sheets.json"
        )
        self._scopes = tuple(scopes)
        self._user_credentials: Credentials | None = None
        self._user_service: Any = None

    # ---- credentials / token management ---------------------------------- #
    @staticmethod
    def _resolve_client_secret_path(
        client_secret_path: str | os.PathLike[str] | None,
    ) -> Path:
        if client_secret_path:
            path = Path(client_secret_path).expanduser().resolve()
        else:
            env = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            if env:
                path = Path(env).expanduser().resolve()
            else:
                candidates = sorted(
                    p for p in Path(__file__).resolve().parent.glob("client_secret_*.json")
                )
                if not candidates:
                    raise SheetsAuthError(
                        "OAuth2 client_secret не найден. Укажите путь явно, "
                        "или положите client_secret_*.json рядом с модулем."
                    )
                path = candidates[0]
        if not path.is_file():
            raise SheetsAuthError(f"Файл secret не найден: {path}")
        return path

    @property
    def credentials(self) -> Credentials:
        if self._user_credentials is None or not self._user_credentials.valid:
            self._user_credentials = self._refresh_or_run_flow()
        return self._user_credentials

    def _refresh_or_run_flow(self) -> Credentials:
        if self._token_path.is_file():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), scopes=list(self._scopes)
                )
                if creds.valid:
                    return creds
                if creds.expired and creds.refresh_token:
                    try:
                        from google.auth.transport.requests import Request
                        creds.refresh(Request())
                        self._save_token(creds)
                        return creds
                    except Exception:
                        pass
            except Exception:
                pass
        return self._run_flow()

    def _run_flow(self, *, open_browser: bool = True) -> Credentials:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_secret_path), scopes=list(self._scopes)
        )
        try:
            creds = flow.run_local_server(host="localhost", port=0, open_browser=open_browser)
        except Exception as exc:
            text = str(exc).lower()
            if "access_denied" in text or "access denied" in text:
                raise SheetsAuthError(_ACCESS_DENIED_HINT) from exc
            if open_browser:
                print(f"! Не удалось открыть браузер ({exc}).")
                return self._run_flow(open_browser=False)
            raise SheetsAuthError(f"OAuth2 failed: {exc}") from exc
        self._save_token(creds)
        return creds

    def reauth(self) -> Credentials:
        self._token_path.unlink(missing_ok=True)
        self._user_credentials = None
        self._user_service = None
        return self.credentials

    def _save_token(self, creds: Credentials) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json(), encoding="utf-8")

    @property
    def user_email(self) -> str:
        try:
            svc = self._user_service or self._build_user_service()
            resp = svc.about().get(fields="user").execute()
            return resp.get("user", {}).get("emailAddress", "unknown")
        except Exception:
            return "unknown"

    def _build_user_service(self) -> Any:
        if self._user_service is None:
            self._user_service = build(
                "sheets", "v4", credentials=self.credentials, cache_discovery=False
            )
        return self._user_service

    @property
    def service(self) -> Any:
        if self._user_service is None:
            self._user_service = build(
                "sheets", "v4", credentials=self.credentials, cache_discovery=False
            )
        return self._user_service

    # ---- formatting ------------------------------------------------------ #
    @staticmethod
    def _parse_a1_to_grid(range_name: str) -> dict[str, int]:
        """A1-диапазон → grid range dict."""
        cells = range_name.split("!")[-1] if "!" in range_name else range_name
        if not cells or ":" not in cells:
            return {"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1}
        start, end = cells.split(":", 1)
        m1 = re.match(r"([A-Z]+)(\d+)", start.upper())
        m2 = re.match(r"([A-Z]+)(\d+)", end.upper())
        if not m1 or not m2:
            return {"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1}

        def col_idx(col: str) -> int:
            r = 0
            for ch in col.upper():
                r = r * 26 + (ord(ch) - ord("A") + 1)
            return r - 1

        return {
            "startRowIndex": int(m1.group(2)) - 1,
            "endRowIndex": int(m2.group(2)),
            "startColumnIndex": col_idx(m1.group(1)),
            "endColumnIndex": col_idx(m2.group(1)) + 1,
        }

    def _make_grid_range(self, range_name: str, *, sheet: str | None = None) -> dict[str, Any]:
        cells = self._parse_a1_to_grid(range_name)
        cells["sheetId"] = self.sheet_id(sheet)
        return cells

    def format_range(
        self,
        range_name: str,
        *,
        sheet: str | None = None,
        bold: bool = False,
        italic: bool = False,
        font_size: int | None = None,
        text_color: tuple[float, float, float, float] | None = None,
        background_color: tuple[float, float, float, float] | None = None,
        horizontal_alignment: str | None = None,
        wrap_strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Применить форматирование к диапазону (повторяет для каждой ячейки).

        Цвета — RGBA от 0.0 до 1.0. Например: (1.0, 0.0, 0.0, 1.0) = красный.
        """
        grid = self._make_grid_range(range_name, sheet=sheet)
        if not grid or grid.get("sheetId", 0) == 0:
            return []

        # Build userEnteredFormat
        fmt: dict[str, Any] = {}
        fmt_fields: list[str] = []

        # textFormat
        tf: dict[str, Any] = {}
        if bold:
            tf["bold"] = True
            fmt_fields.append("userEnteredFormat.textFormat.bold")
        if italic:
            tf["italic"] = True
            fmt_fields.append("userEnteredFormat.textFormat.italic")
        if font_size is not None:
            tf["fontSize"] = font_size
            fmt_fields.append("userEnteredFormat.textFormat.fontSize")
        if text_color is not None:
            tf["foregroundColor"] = {
                "red": text_color[0], "green": text_color[1],
                "blue": text_color[2], "alpha": text_color[3],
            }
            fmt_fields.append("userEnteredFormat.textFormat.foregroundColor")
        if tf:
            fmt["textFormat"] = tf

        if background_color is not None:
            fmt["backgroundColor"] = {
                "red": background_color[0], "green": background_color[1],
                "blue": background_color[2], "alpha": background_color[3],
            }
            fmt_fields.append("userEnteredFormat.backgroundColor")

        if horizontal_alignment:
            fmt["horizontalAlignment"] = horizontal_alignment
            fmt_fields.append("userEnteredFormat.horizontalAlignment")

        if wrap_strategy:
            fmt["wrapStrategy"] = wrap_strategy
            fmt_fields.append("userEnteredFormat.wrapStrategy")

        if not fmt_fields:
            return []

        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [{
                        "repeatCell": {
                            "range": grid,
                            "cell": {"userEnteredFormat": fmt},
                            "fields": ",".join(fmt_fields),
                        }
                    }]
                },
            )
        ).get("writeResponses", [])

    def set_column_width(self, range_name: str, width: int, *, sheet: str | None = None) -> list[dict[str, Any]]:
        """Установить ширину столбцов в пикселях."""
        grid = self._make_grid_range(range_name, sheet=sheet)
        if not grid:
            return []
        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [{
                        "updateDimensionProperties": {
                            "range": grid,
                            "properties": {"pixelSize": width},
                            "fields": "pixelSize",
                        }
                    }]
                },
            )
        ).get("writeResponses", [])

    def freeze_panes(self, row_count: int = 1, col_count: int = 0, *, sheet: str | None = None) -> list[dict[str, Any]]:
        """Закрепить строки/столбцы."""
        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [{
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": self.sheet_id(sheet),
                                "gridProperties": {
                                    "frozenRowCount": row_count,
                                    "frozenColumnCount": col_count,
                                },
                            },
                            "fields": "gridProperties",
                        }
                    }]
                },
            )
        ).get("writeResponses", [])

    def set_sheet_tab_color(self, r: float = 1.0, g: float = 1.0, b: float = 1.0, a: float = 1.0, *, sheet: str | None = None) -> list[dict[str, Any]]:
        """Цвет вкладки."""
        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [{
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": self.sheet_id(sheet),
                                "tabColor": {"red": r, "green": g, "blue": b, "alpha": a},
                            },
                            "fields": "tabColor",
                        }
                    }]
                },
            )
        ).get("writeResponses", [])

    # ---- factory --------------------------------------------------------- #
    @classmethod
    def create_spreadsheet(
        cls,
        title: str,
        *,
        client_secret_path: str | os.PathLike[str] | None = None,
        token_path: str | os.PathLike[str] | None = None,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ) -> str:
        """Создать таблицу от имени пользователя, вернуть ID."""
        client = cls(
            client_secret_path=client_secret_path,
            token_path=token_path,
            scopes=scopes,
        )
        response = client._execute(
            client.service.spreadsheets().create(body={"properties": {"title": title}})
        )
        return response["spreadsheetId"]


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    CREDENTIALS_PATH = Path(__file__).with_name(
        os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "client_secret_desktop.json")
    )
    TOKEN_PATH = Path(__file__).with_name("token_sheets.json")

    print("Google Sheets User Client")
    print("=" * 50)

    try:
        sheets = GoogleSheetsUserClient(CREDENTIALS_PATH, TOKEN_PATH)
        print(f"Authenticated as: {sheets.user_email}")
    except SheetsAuthError as e:
        raise SystemExit(f"\n! {e}")

    # Demo: create spreadsheet, write data, format
    sid = GoogleSheetsUserClient.create_spreadsheet(
        f"Test {__import__('time').strftime('%Y-%m-%d %H:%M')}",
        CREDENTIALS_PATH, TOKEN_PATH,
    )
    print(f"Created: {sid}")

    with GoogleSheetsUserClient(CREDENTIALS_PATH, TOKEN_PATH, sid) as s:
        s.write("A1:C1", [["Name", "Age", "City"]])
        s.format_range("A1:C1", bold=True,
                        background_color=(0.2, 0.6, 1.0, 1.0),
                        text_color=(1.0, 1.0, 1.0, 1.0),
                        horizontal_alignment="CENTER")
        s.write("A2:C4", [["Alice", 30, "NYC"], ["Bob", 25, "London"], ["Charlie", 35, "Paris"]])
        s.set_column_width("A1:C4", 150)
        s.freeze_panes(row_count=1)
        print("Done!")
