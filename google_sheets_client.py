"""
google_sheets_client.py
=======================

Reusable OOP client for the Google Sheets API v4 (service-account auth).

The module is self-contained: copy it into any other project and use it as

    from google_sheets_client import GoogleSheetsClient

    with GoogleSheetsClient("service_account.json", "<spreadsheet_id>") as sheets:
        rows = sheets.read_all()
        sheets.append_row(["Ivan", 30])
        sheets.update_cell(2, 1, "Petr")
        sheets.delete_row(5)

Only dependencies: google-api-python-client, google-auth.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

__all__ = [
    "GoogleSheetsClient",
    "GoogleSheetsError",
    "SpreadsheetNotFound",
    "SheetNotFound",
    "col_number_to_letter",
    "col_letter_to_number",
]

# Drive scope is only needed by `list_spreadsheets()` (to discover spreadsheet
# ids shared with the service account). CRUD itself works with spreadsheets only.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

Value = Any
Row = Sequence[Value]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class GoogleSheetsError(RuntimeError):
    """Any error returned by the Sheets API or raised by this client."""


class SpreadsheetNotFound(GoogleSheetsError):
    """Spreadsheet id is wrong, or the file is not shared with the service account."""


class SheetNotFound(GoogleSheetsError):
    """Worksheet (tab) with the requested title does not exist."""


# --------------------------------------------------------------------------- #
# A1-notation helpers
# --------------------------------------------------------------------------- #
def col_number_to_letter(number: int) -> str:
    """1 -> 'A', 27 -> 'AA'."""
    if number < 1:
        raise ValueError(f"Column number must be >= 1, got {number}")
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def col_letter_to_number(letters: str) -> int:
    """'A' -> 1, 'AA' -> 27."""
    letters = letters.strip().upper()
    if not letters or not letters.isalpha():
        raise ValueError(f"Invalid column letters: {letters!r}")
    return sum(
        (ord(ch) - ord("A") + 1) * 26 ** i for i, ch in enumerate(reversed(letters))
    )


def quote_sheet_name(title: str) -> str:
    """Wrap a sheet title for safe use inside an A1 range."""
    return "'" + title.replace("'", "''") + "'"


def _to_2d(values: Any) -> list[list[Value]]:
    """Normalize a scalar / 1D / 2D payload into the 2D list the API expects."""
    if values is None:
        return [[None]]
    if not isinstance(values, (list, tuple)):
        return [[values]]
    if not values:
        return [[]]
    if all(isinstance(item, (list, tuple)) for item in values):
        return [list(row) for row in values]
    return [[item] for item in values]


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class GoogleSheetsClient:
    """CRUD facade over the Google Sheets API.

    Args:
        credentials_path:
            Path to the service-account JSON key. Defaults to
            ``GOOGLE_APPLICATION_CREDENTIALS`` env var, then to the first
            ``*.json`` key found next to this module.
        spreadsheet_id:
            Spreadsheet id (the long string between ``/d/`` and ``/edit``
            in the sheet URL). A full URL is accepted as well.
        sheet_name:
            Active worksheet title. ``None`` / ``""`` resolves to the first tab.
        scopes: API scopes; defaults to :data:`DEFAULT_SCOPES`.
        value_input_option: ``RAW`` or ``USER_ENTERED`` (default), i.e. whether
            written strings like ``=SUM(A1:A2)`` or ``01/02/2026`` are parsed.
    """

    # ---- lifecycle ------------------------------------------------------- #
    def __init__(
        self,
        credentials_path: str | os.PathLike[str] | None = None,
        spreadsheet_id: str = "",
        sheet_name: str | None = None,
        *,
        scopes: Sequence[str] = DEFAULT_SCOPES,
        value_input_option: str = "USER_ENTERED",
    ) -> None:
        self._credentials_path = self._resolve_credentials_path(credentials_path)
        self._spreadsheet_id = self.parse_spreadsheet_id(spreadsheet_id)
        self._sheet_name = sheet_name or None
        self._scopes = tuple(scopes)
        self._value_input_option = value_input_option
        self._credentials: service_account.Credentials | None = None
        self._service: Any = None

    @staticmethod
    def _resolve_credentials_path(
        credentials_path: str | os.PathLike[str] | None,
    ) -> Path:
        if credentials_path:
            path = Path(credentials_path).expanduser().resolve()
        else:
            env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if env:
                path = Path(env).expanduser().resolve()
            else:
                candidates = sorted(
                    p
                    for p in Path(__file__).resolve().parent.glob("*.json")
                    if "service_account" in p.read_text(encoding="utf-8", errors="ignore")
                )
                if not candidates:
                    raise GoogleSheetsError(
                        "Service-account key not found: pass credentials_path "
                        "explicitly or set GOOGLE_APPLICATION_CREDENTIALS."
                    )
                path = candidates[0]
        if not path.is_file():
            raise GoogleSheetsError(f"Credentials file not found: {path}")
        return path

    @staticmethod
    def parse_spreadsheet_id(value: str) -> str:
        """Accept a raw id or a full ``https://docs.google.com/spreadsheets/d/<id>/...`` URL."""
        value = (value or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            marker = "/spreadsheets/d/"
            if marker in value:
                tail = value.split(marker, 1)[1]
                return tail.split("/")[0].split("?")[0].split("#")[0]
            return value
        return value

    @property
    def credentials(self) -> service_account.Credentials:
        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                str(self._credentials_path), scopes=list(self._scopes)
            )
        return self._credentials

    @property
    def service(self) -> Any:
        """Lazily built google-api-python-client resource."""
        if self._service is None:
            self._service = build(
                "sheets",
                "v4",
                credentials=self.credentials,
                cache_discovery=False,
            )
        return self._service

    @property
    def service_account_email(self) -> str:
        return self.credentials.service_account_email

    @property
    def spreadsheet_id(self) -> str:
        return self._spreadsheet_id

    @property
    def spreadsheet_url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}"

    @property
    def sheet_name(self) -> str:
        """Active worksheet title (resolved lazily to the first tab)."""
        if self._sheet_name is None:
            self._sheet_name = self.sheet_titles()[0]
        return self._sheet_name

    def use_sheet(self, title: str) -> "GoogleSheetsClient":
        """Switch the active worksheet; raises :class:`SheetNotFound` if absent."""
        titles = self.sheet_titles()
        if title not in titles:
            raise SheetNotFound(
                f"Sheet {title!r} not found. Existing sheets: {', '.join(titles)}"
            )
        self._sheet_name = title
        return self

    def __enter__(self) -> "GoogleSheetsClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._service is not None:
            self._service.close()
            self._service = None

    # ---- internals ------------------------------------------------------- #
    @staticmethod
    def _describe_http_error(exc: HttpError) -> str:
        """Short, human-readable message out of a raw HttpError payload."""
        reason = ""
        try:
            payload = json.loads(exc.content.decode("utf-8"))
            reason = payload.get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001 - payload shape is not guaranteed
            reason = str(exc)
        status = getattr(exc.resp, "status", None)
        hints = {
            403: (
                " Share the spreadsheet with the service-account email and make "
                "sure the Google Sheets API is enabled in the project."
            ),
            404: (
                " Check the spreadsheet id, the sheet title and the sharing "
                "settings."
            ),
        }
        return f"Google Sheets API error {status}: {reason}{hints.get(status, '')}"

    def _execute(self, request: Any, *, attempts: int = 5) -> Any:
        """Execute a request with exponential backoff on transient errors."""
        delay = 1.0
        for attempt in range(1, attempts + 1):
            try:
                return request.execute()
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                if status in _RETRYABLE_STATUS and attempt < attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                message = self._describe_http_error(exc)
                if status == 404:
                    raise SpreadsheetNotFound(message) from exc
                raise GoogleSheetsError(message) from exc
            except OSError as exc:  # network-level failure
                if attempt < attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise GoogleSheetsError(f"Network error: {exc}") from exc
        raise GoogleSheetsError("Request failed after retries")

    def _resolve_range(self, range_name: str | None) -> str:
        """Build an A1 range on the active sheet: ``read('A1:C3')`` -> ``'Sheet1'!A1:C3``."""
        target = (range_name or "").strip()
        if not target:
            return quote_sheet_name(self.sheet_name)
        if "!" in target:  # already sheet-qualified
            sheet_part, cells = target.split("!", 1)
            if not sheet_part.startswith("'"):
                sheet_part = quote_sheet_name(sheet_part)
            return f"{sheet_part}!{cells}"
        return f"{quote_sheet_name(self.sheet_name)}!{target}"

    # ---- meta / READ ----------------------------------------------------- #
    def spreadsheet_metadata(self, *, fields: str = "sheets.properties,properties") -> Any:
        return self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id, fields=fields
            )
        )

    def sheet_titles(self) -> list[str]:
        meta = self.spreadsheet_metadata()
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def sheet_properties(self, title: str | None = None) -> dict[str, Any]:
        title = title or self.sheet_name
        for sheet in self.spreadsheet_metadata().get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == title:
                return props
        raise SheetNotFound(f"Sheet {title!r} not found")

    def grid_size(self, title: str | None = None) -> tuple[int, int]:
        """(rows, columns) of the worksheet grid."""
        grid = self.sheet_properties(title).get("gridProperties", {})
        return int(grid.get("rowCount", 0)), int(grid.get("columnCount", 0))

    def read(
        self,
        range_name: str | None = None,
        *,
        sheet: str | None = None,
        value_render_option: str = "FORMATTED_VALUE",
        date_time_render_option: str = "FORMATTED_STRING",
    ) -> list[list[Any]]:
        """Read a range (defaults to the whole active sheet) as a list of rows.

        ``read('A1:C10')``, ``read('Sheet2!A:B')``, ``read()`` - all supported.
        Empty cells are returned as ``None``.
        """
        target = self._resolve_range(f"{sheet}!{range_name}" if sheet else range_name)
        response = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self._spreadsheet_id,
                range=target,
                valueRenderOption=value_render_option,
                dateTimeRenderOption=date_time_render_option,
            )
        )
        return [list(row) for row in response.get("values", [])]

    def read_all(
        self, sheet: str | None = None, *, value_render_option: str = "FORMATTED_VALUE"
    ) -> list[list[Any]]:
        """Read every non-empty cell of the worksheet."""
        rows, cols = self.grid_size(sheet)
        if not rows or not cols:
            return []
        range_name = f"A1:{col_number_to_letter(cols)}{rows}"
        return self.read(range_name, sheet=sheet, value_render_option=value_render_option)

    def read_as_dicts(
        self, range_name: str | None = None, *, sheet: str | None = None
    ) -> list[dict[str, Any]]:
        """Read a range using its first row as dict keys."""
        rows = self.read(range_name, sheet=sheet)
        if not rows:
            return []
        headers = [str(h) for h in rows[0]]
        result: list[dict[str, Any]] = []
        for row in rows[1:]:
            padded = list(row) + [None] * (len(headers) - len(row))
            result.append(dict(zip(headers, padded)))
        return result

    def get_cell(self, row: int, column: int | str, *, sheet: str | None = None) -> Any:
        """Read one cell. ``get_cell(2, 3)`` or ``get_cell(2, 'C')``."""
        col = column if isinstance(column, str) else col_number_to_letter(column)
        values = self.read(f"{col}{row}:{col}{row}", sheet=sheet)
        return values[0][0] if values and values[0] else None

    def iter_rows(
        self, *, start_row: int = 1, sheet: str | None = None
    ) -> Iterator[tuple[int, list[Any]]]:
        """Yield ``(row_number, row_values)`` for every non-empty row."""
        for index, row in enumerate(self.read_all(sheet=sheet), start=1):
            if index >= start_row:
                yield index, row

    def count_rows(self, sheet: str | None = None) -> int:
        """Number of non-empty rows."""
        return len(self.read_all(sheet=sheet))

    def find_in_column(
        self, value: Any, column: int | str, *, sheet: str | None = None
    ) -> list[int]:
        """Row numbers where ``str(cell) == str(value)`` inside a column."""
        col = column if isinstance(column, str) else col_number_to_letter(column)
        cells = self.read(f"{col}:{col}", sheet=sheet)
        return [
            index
            for index, row in enumerate(cells, start=1)
            if row and str(row[0]) == str(value)
        ]

    # ---- CREATE ---------------------------------------------------------- #
    def write(
        self,
        range_name: str,
        values: Sequence[Sequence[Value]],
        *,
        sheet: str | None = None,
        value_input_option: str | None = None,
    ) -> dict[str, Any]:
        """Overwrite a range with a 2D list (creates values outside the grid)."""
        response = self._execute(
            self.service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=self._resolve_range(f"{sheet}!{range_name}" if sheet else range_name),
                valueInputOption=value_input_option or self._value_input_option,
                body={"values": [list(row) for row in values]},
            )
        )
        return response.get("updates", {})

    def append(
        self,
        rows: Sequence[Sequence[Value]],
        *,
        sheet: str | None = None,
        value_input_option: str | None = None,
    ) -> dict[str, Any]:
        """Append rows after the last non-empty row of the table."""
        response = self._execute(
            self.service.spreadsheets().values().append(
                spreadsheetId=self._spreadsheet_id,
                range=self._resolve_range(f"{sheet}" if sheet else None),
                valueInputOption=value_input_option or self._value_input_option,
                insertDataOption="INSERT_ROWS",
                body={"values": [list(row) for row in rows]},
            )
        )
        return response.get("updates", {})

    def append_row(self, row: Sequence[Value], *, sheet: str | None = None) -> dict[str, Any]:
        return self.append([row], sheet=sheet)

    def append_dict(
        self, mapping: Mapping[str, Value], *, sheet: str | None = None, headers: Sequence[str] | None = None
    ) -> dict[str, Any]:
        """Append one record. Writes a header row first if the sheet is empty."""
        keys = list(headers or mapping.keys())
        if self.count_rows(sheet) == 0:
            self.write("A1", [keys], sheet=sheet)
        return self.append_row([mapping.get(k) for k in keys], sheet=sheet)

    def create_sheet(self, title: str, *, grid_rows: int = 1000, grid_columns: int = 26) -> str:
        """Add a worksheet tab and return its title."""
        if title in self.sheet_titles():
            raise GoogleSheetsError(f"Sheet {title!r} already exists")
        self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": title,
                                    "gridProperties": {
                                        "rowCount": grid_rows,
                                        "columnCount": grid_columns,
                                    },
                                }
                            }
                        }
                    ]
                },
            )
        )
        return title

    @classmethod
    def create_spreadsheet(
        cls,
        title: str,
        *,
        credentials_path: str | os.PathLike[str] | None = None,
        scopes: Sequence[str] = DEFAULT_SCOPES,
    ) -> str:
        """Create a new spreadsheet owned by the service account, return its id."""
        client = cls(credentials_path, scopes=scopes)
        response = client._execute(  # noqa: SLF001 - internal use by design
            client.service.spreadsheets().create(
                body={"properties": {"title": title}}
            )
        )
        return response["spreadsheetId"]

    # ---- UPDATE ---------------------------------------------------------- #
    def update_cell(
        self, row: int, column: int | str, value: Value, *, sheet: str | None = None
    ) -> dict[str, Any]:
        """Update one cell: ``update_cell(3, 'B', 'ok')``."""
        col = column if isinstance(column, str) else col_number_to_letter(column)
        return self.write(f"{col}{row}", [[value]], sheet=sheet)

    def update_row(
        self, row: int, values: Sequence[Value], *, start_column: int = 1, sheet: str | None = None
    ) -> dict[str, Any]:
        """Update a row starting from ``start_column`` (1-based)."""
        start = col_number_to_letter(start_column)
        end = col_number_to_letter(start_column + len(values) - 1)
        return self.write(f"{start}{row}:{end}{row}", [list(values)], sheet=sheet)

    def update_column(
        self, column: int | str, values: Iterable[Value], *, start_row: int = 1, sheet: str | None = None
    ) -> dict[str, Any]:
        """Update a column starting from ``start_row`` (1-based)."""
        col = column if isinstance(column, str) else col_number_to_letter(column)
        data = list(values)
        return self.write(
            f"{col}{start_row}:{col}{start_row + len(data) - 1}",
            [[value] for value in data],
            sheet=sheet,
        )

    def update_cells(
        self, updates: Mapping[str, Value] | Sequence[tuple[str, Sequence[Sequence[Value]]]]
    ) -> list[dict[str, Any]]:
        """Batch-update several ranges in one API call.

        ``update_cells({'A1': 'x', 'B2:B3': [['a'], ['b']]})``
        """
        items: list[tuple[str, Value]] = (
            list(updates.items()) if isinstance(updates, Mapping) else list(updates)
        )
        data = [
            {"range": self._resolve_range(rng), "values": _to_2d(value)}
            for rng, value in items
        ]
        response = self._execute(
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "valueInputOption": self._value_input_option,
                    "data": data,
                },
            )
        )
        return response.get("updates", [])

    def update_row_by_header(
        self, row: int, mapping: Mapping[str, Value], *, sheet: str | None = None
    ) -> list[dict[str, Any]]:
        """Update cells of a row addressed by header names from row 1."""
        headers = self.read("1:1", sheet=sheet)
        header_row = [str(h) for h in headers[0]] if headers else []
        updates: dict[str, Value] = {}
        for key, value in mapping.items():
            if key not in header_row:
                raise GoogleSheetsError(f"Header {key!r} not found in row 1")
            updates[f"{col_number_to_letter(header_row.index(key) + 1)}{row}"] = value
        return self.update_cells(updates)

    # ---- DELETE ---------------------------------------------------------- #
    def clear(self, range_name: str | None = None, *, sheet: str | None = None) -> list[str]:
        """Clear values (not formatting) of a range; whole sheet by default.

        Returns the list of cleared A1 ranges.
        """
        response = self._execute(
            self.service.spreadsheets().values().clear(
                spreadsheetId=self._spreadsheet_id,
                range=self._resolve_range(f"{sheet}" if sheet else range_name),
                body={},
            )
        )
        return list(response.get("clearedRanges", []))

    def _delete_dimension(self, dimension: str, start: int, count: int) -> Any:
        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": self.sheet_id(),
                                    "dimension": dimension,
                                    "startIndex": start - 1,
                                    "endIndex": start - 1 + count,
                                }
                            }
                        }
                    ]
                },
            )
        )

    def sheet_id(self, title: str | None = None) -> int:
        return int(self.sheet_properties(title).get("sheetId", 0))

    def delete_row(self, row: int, *, count: int = 1, sheet: str | None = None) -> Any:
        """Delete ``count`` rows starting from 1-based ``row``."""
        previous = self._sheet_name
        try:
            if sheet:
                self.use_sheet(sheet)
            return self._delete_dimension("ROWS", row, count)
        finally:
            self._sheet_name = previous

    def delete_column(self, column: int | str, *, count: int = 1, sheet: str | None = None) -> Any:
        """Delete ``count`` columns starting from ``column`` (1-based number or letter)."""
        index = column if isinstance(column, int) else col_letter_to_number(column)
        previous = self._sheet_name
        try:
            if sheet:
                self.use_sheet(sheet)
            return self._delete_dimension("COLUMNS", index, count)
        finally:
            self._sheet_name = previous

    def delete_sheet(self, title: str) -> Any:
        """Remove a worksheet tab."""
        target = self.sheet_id(title)
        return self._execute(
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"deleteSheet": {"sheetId": target}}]},
            )
        )

    # ---- discovery helper ------------------------------------------------ #
    @staticmethod
    def list_spreadsheets(
        credentials_path: str | os.PathLike[str] | None = None,
        *,
        query: str = "mimeType='application/vnd.google-apps.spreadsheet'",
    ) -> list[dict[str, str]]:
        """Files visible to the service account: ``[{'id': ..., 'name': ...}, ...]``.

        Requires the Drive API to be enabled and ``drive.readonly`` in the scopes.
        """
        from googleapiclient.discovery import build as _build  # local import: optional dep

        credentials = service_account.Credentials.from_service_account_file(
            str(GoogleSheetsClient._resolve_credentials_path(credentials_path)),
            scopes=list(DEFAULT_SCOPES),
        )
        drive = _build("drive", "v3", credentials=credentials, cache_discovery=False)
        try:
            response = (
                drive.files()
                .list(q=query, fields="files(id,name)", pageSize=100)
                .execute()
            )
        except HttpError as exc:
            raise GoogleSheetsError(
                "Cannot list spreadsheets: the Google Drive API is not enabled for "
                "this project. Set SPREADSHEET_ID manually "
                f"(https://console.cloud.google.com/apis/api/drive.googleapis.com). "
                f"(HTTP {getattr(exc.resp, 'status', '?')})"
            ) from exc
        finally:
            drive.close()
        return [{"id": f["id"], "name": f.get("name", "")} for f in response.get("files", [])]


# --------------------------------------------------------------------------- #
# Entry point: read every cell of the sheet and print it to the console
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # Credentials live in the project next to this module - the client finds
    # them automatically, the path is given here only for clarity.
    CREDENTIALS_PATH = Path(__file__).with_name("excel-factory-511418-a6cad01b8b8a.json")

    # Id from the sheet URL: https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
    # A full URL works too; env GOOGLE_SPREADSHEET_ID overrides this value.
    SPREADSHEET_ID = "1TVSodYJHqf0ssgYRBIN-msDYe5xPLw3y8IUG8P8fx8s"
    # Empty string -> the first worksheet tab is used.
    SHEET_NAME = ""

    spreadsheet_id = GoogleSheetsClient.parse_spreadsheet_id(
        os.getenv("GOOGLE_SPREADSHEET_ID", SPREADSHEET_ID)
    )
    credentials = GoogleSheetsClient(CREDENTIALS_PATH)
    print(f"Service account : {credentials.service_account_email}")
    credentials.close()

    if not spreadsheet_id:
        # Not configured yet - try to discover sheets shared with the account.
        try:
            available = GoogleSheetsClient.list_spreadsheets(CREDENTIALS_PATH)
        except GoogleSheetsError as error:
            available = []
            print(f"! {error}")
        if not available:
            raise SystemExit(
                "\nSPREADSHEET_ID is not set.\n"
                f"  1) Share the spreadsheet with "
                f"{GoogleSheetsClient(CREDENTIALS_PATH).service_account_email} "
                "(editor access).\n"
                "  2) Copy the id from https://docs.google.com/spreadsheets/d/<ID>/edit\n"
                "     into SPREADSHEET_ID above (or into GOOGLE_SPREADSHEET_ID)."
            )
        print("Spreadsheets available to the service account:")
        for item in available:
            print(f"  - {item['name'] or '(untitled)'} -> {item['id']}")
        spreadsheet_id = available[0]["id"]
        print(f"Taking the first one: {spreadsheet_id}\n")

    with GoogleSheetsClient(CREDENTIALS_PATH, spreadsheet_id, SHEET_NAME or None) as sheets:
        if SHEET_NAME:
            sheets.use_sheet(SHEET_NAME)

        print(f"Spreadsheet     : {sheets.spreadsheet_url}")
        print(f"Worksheets      : {', '.join(sheets.sheet_titles())}")
        print(f"Active sheet    : {sheets.sheet_name}")

        # --- CHECK: read all cells and print them -------------------------- #
        cells = sheets.read_all()

        if not cells:
            print("The sheet is empty - nothing to print.")
        else:
            total_cols = max(len(row) for row in cells)
            max_val_len = max(
                (len(str(cell)) for row in cells for cell in row if cell is not None),
                default=4,
            )
            max_val_len = max(max_val_len, 6)

            header = "     " + " | ".join(
                col_number_to_letter(i).ljust(max_val_len)
                for i in range(1, total_cols + 1)
            )
            print("\n" + header)
            print("-" * len(header))

            for row_number, row in enumerate(cells, start=1):
                padded = list(row) + [None] * (total_cols - len(row))
                line = " | ".join(
                    ("" if cell is None else str(cell)).ljust(max_val_len)
                    for cell in padded
                )
                print(f"{row_number:>3}  {line}")

            filled = sum(1 for row in cells for cell in row if cell is not None and str(cell).strip())
            print(
                f"\nRows: {len(cells)}, "
                f"columns: {total_cols}, "
                f"filled cells: {filled}"
            )
