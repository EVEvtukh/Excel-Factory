"""
document_builder.py
===================

Builds a "Word-like document" layout inside a Google Sheets worksheet:
a grid of values plus a list of Sheets-API formatting requests.

Layout model
------------
column A  -> left page margin (narrow, empty)
columns B..H -> the "page" (7 content columns)
column I  -> right page margin (narrow, empty)

The builder exposes document primitives (title, heading, paragraph, table,
signature, ...) and produces:

    spec = doc.build()
    spec.values        2D list for values().update
    spec.requests      batchUpdate requests (merge, format, borders, sizes)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

# ---------------------------------------------------------------- constants
MARGIN_COL_LEFT = 1   # A
FIRST_COL = 2         # B
LAST_COL = 8          # H
MARGIN_COL_RIGHT = 9  # I
CONTENT_COLS = LAST_COL - FIRST_COL + 1

FONT = "Arial"

COLOR_INK = "1F3864"       # headings / title
COLOR_TEXT = "262626"      # body text
COLOR_MUTED = "7F7F7F"     # captions, footer
COLOR_HEADER_BG = "2F5597"  # table header
COLOR_SECTION_BG = "D9E2F3"
COLOR_ZEBRA = "F2F6FC"
COLOR_TOTAL_BG = "DDEBF7"
COLOR_BORDER = "8EAADB"
COLOR_LINE = "2F5597"
COLOR_POSITIVE = "1E7B34"
COLOR_NEGATIVE = "B00020"

MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек"]

NF_MONEY = '#,##0.00"{unit}"'
NF_INT = "#,##0"
NF_PERCENT = '0.0"%"'
NF_SCORE = "0.00"


# ------------------------------------------------------------------- helpers
def _color(hex_str: str) -> dict[str, float]:
    return {
        "red": int(hex_str[0:2], 16) / 255,
        "green": int(hex_str[2:4], 16) / 255,
        "blue": int(hex_str[4:6], 16) / 255,
    }


def short_date(d: date) -> str:
    """01.10.2026 -> '1 окт' (safe plain text, never re-parsed by Sheets)."""
    return f"{d.day} {MONTHS_SHORT[d.month - 1]}"


def long_date(d: date) -> str:
    """Safe textual date: Sheets must not reinterpret it as a serial number."""
    return f"{d.day:02d}.{d.month:02d}.{d.year} г."


# ------------------------------------------------------------------ dataclass
@dataclass
class TableInfo:
    """Row coordinates of a rendered table (1-based, inclusive)."""
    header_row: int
    first_body: int
    last_body: int
    total_row: int | None
    spans: list[int]

    def column_span(self, index: int) -> tuple[int, int]:
        """(first_col, last_col) of the logical column with the given index."""
        start = FIRST_COL + sum(self.spans[:index])
        return start, start + self.spans[index] - 1

    def column_anchor(self, index: int) -> int:
        """Left-most (value-holding) column of a logical column."""
        return FIRST_COL + sum(self.spans[:index])

    @property
    def data_range(self) -> tuple[int, int]:
        """(first_body, last_body)"""
        return self.first_body, self.last_body


@dataclass
class DocumentSpec:
    values: list[list[Any]]
    requests: list[dict[str, Any]]
    rows: int
    columns: int = MARGIN_COL_RIGHT


class ReportDocument:
    """Composable Word-like layout rendered into a sheet grid."""

    def __init__(self, sheet_id: int) -> None:
        self.sheet_id = sheet_id
        self._values: dict[tuple[int, int], Any] = {}
        self._requests: list[dict[str, Any]] = []
        self._row_heights: dict[int, int] = {}
        self._row = 1

    # ---- low level ------------------------------------------------------- #
    @property
    def row(self) -> int:
        return self._row

    def _grid_range(self, r1: int, c1: int, r2: int, c2: int) -> dict[str, int]:
        return {
            "sheetId": self.sheet_id,
            "startRowIndex": r1 - 1,
            "endRowIndex": r2,
            "startColumnIndex": c1 - 1,
            "endColumnIndex": c2,
        }

    def put(self, row: int, col: int, value: Any) -> None:
        self._values[(row, col)] = value

    def merge(self, r1: int, c1: int, r2: int, c2: int) -> None:
        if (r2, c2) > (r1, c1):
            self._requests.append(
                {"mergeCells": {"range": self._grid_range(r1, c1, r2, c2),
                                "mergeType": "MERGE_ALL"}}
            )

    def style(
        self,
        r1: int, c1: int, r2: int, c2: int,
        *,
        bold: bool | None = None,
        italic: bool | None = None,
        size: int | float | None = None,
        fg: str | None = None,
        bg: str | None = None,
        align: str | None = None,
        valign: str | None = None,
        wrap: bool | None = None,
        number_format: str | None = None,
        font: str | None = FONT,
    ) -> None:
        text_format: dict[str, Any] = {}
        if bold is not None:
            text_format["bold"] = bold
        if italic is not None:
            text_format["italic"] = italic
        if size is not None:
            text_format["fontSize"] = size
        if fg is not None:
            text_format["foregroundColor"] = _color(fg)
        if font:
            text_format["fontFamily"] = font
        cell_format: dict[str, Any] = {}
        if text_format:
            cell_format["textFormat"] = text_format
        if align is not None:
            cell_format["horizontalAlignment"] = align
        if valign is not None:
            cell_format["verticalAlignment"] = valign
        if wrap is not None:
            cell_format["wrapStrategy"] = "WRAP" if wrap else "OVERFLOW_CELL"
        if bg is not None:
            cell_format["backgroundColor"] = _color(bg)
        if number_format:
            cell_format["numberFormat"] = {
                "type": "NUMBER", "pattern": number_format,
            }
        self._requests.append({
            "repeatCell": {
                "range": self._grid_range(r1, c1, r2, c2),
                "cell": {"userEnteredFormat": cell_format},
                "fields": self._fields_for(cell_format),
            }
        })

    @staticmethod
    def _fields_for(cell_format: dict[str, Any]) -> str:
        """Field mask relative to a Cell: 'userEnteredFormat.textFormat.bold,...'."""
        expandable = {"textFormat", "numberFormat"}
        parts: list[str] = []
        for key, value in cell_format.items():
            if isinstance(value, dict) and key in expandable:
                parts.extend(f"userEnteredFormat.{key}.{sub}" for sub in value)
            else:
                parts.append(f"userEnteredFormat.{key}")
        return ",".join(parts)

    def borders(
        self, r1: int, c1: int, r2: int, c2: int,
        *,
        style: str = "SOLID",
        color: str = COLOR_BORDER,
        width: int = 1,
        edges: Sequence[str] = ("ALL",),
    ) -> None:
        """Draw borders. Sheets has no border request: borders live in CellFormat."""
        edge_map = {
            "ALL": ("top", "bottom", "left", "right"),
            "FRAME": ("top", "bottom", "left", "right"),
            "BOTTOM": ("bottom",),
            "TOP": ("top",),
            "LEFT": ("left",),
            "RIGHT": ("right",),
        }
        sides: list[str] = []
        for edge in edges:
            sides.extend(edge_map.get(edge.upper(), [edge.lower()]))
        border = {"style": style, "width": width, "color": _color(color)}
        self._requests.append({
            "repeatCell": {
                "range": self._grid_range(r1, c1, r2, c2),
                "cell": {"userEnteredFormat": {"borders": {s: border for s in set(sides)}}},
                "fields": ",".join(f"userEnteredFormat.borders.{s}" for s in set(sides)),
            }
        })

    def row_height(self, row: int, pixels: int) -> None:
        self._row_heights[row] = max(self._row_heights.get(row, 0), pixels)

    def column_width(self, col: int, pixels: int) -> None:
        self._requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": self.sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col - 1,
                    "endIndex": col,
                },
                "properties": {"pixelSize": pixels},
                "fields": "pixelSize",
            }
        })

    # ---- page setup ------------------------------------------------------ #
    def page(self, *, tab_color: str = "2F5597") -> None:
        """Margins, fonts, gridlines, print setup."""
        for col, px in ((MARGIN_COL_LEFT, 28), (MARGIN_COL_RIGHT, 28)):
            self.column_width(col, px)
        for col, px in ((2, 148), (3, 96), (4, 96), (5, 96), (6, 96), (7, 96), (8, 96)):
            self.column_width(col, px)
        self._requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": self.sheet_id,
                               "gridProperties": {"hideGridlines": True}},
                "fields": "gridProperties.hideGridlines",
            }
        })
        self._requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": self.sheet_id, "tabColor": _color(tab_color)},
                "fields": "tabColor",
            }
        })

    # ---- primitives ------------------------------------------------------ #
    def spacer(self, pixels: int = 10) -> int:
        self.row_height(self._row, pixels)
        self._row += 1
        return self._row - 1

    def line(self, *, weight: int = 3, color: str = COLOR_LINE, pixels: int = 6) -> int:
        row = self._row
        self.merge(row, FIRST_COL, row, LAST_COL)
        self.borders(row, FIRST_COL, row, LAST_COL, style="SOLID",
                     color=color, width=weight, edges=("BOTTOM",))
        self.row_height(row, pixels)
        self._row += 1
        return row

    def text(
        self,
        value: str,
        *,
        size: int = 10,
        bold: bool = False,
        italic: bool = False,
        color: str = COLOR_TEXT,
        align: str = "LEFT",
        span: int = CONTENT_COLS,
        height: int = 18,
        wrap: bool = False,
        indent: int = 0,
    ) -> int:
        row = self._row
        self.put(row, FIRST_COL + indent, value)
        self.merge(row, FIRST_COL + indent, row, FIRST_COL + indent + span - 1)
        self.style(row, FIRST_COL + indent, row, FIRST_COL + indent + span - 1,
                   bold=bold, italic=italic, size=size, fg=color,
                   align=align, valign="TOP", wrap=wrap)
        self.row_height(row, height)
        self._row += 1
        return row

    def heading(self, value: str, *, level: int = 1) -> int:
        row = self._row
        if level == 1:
            self.put(row, FIRST_COL, value)
            self.merge(row, FIRST_COL, row, LAST_COL)
            self.style(row, FIRST_COL, row, LAST_COL, bold=True, size=13,
                       fg=COLOR_INK, align="LEFT", valign="BOTTOM", bg=COLOR_SECTION_BG)
            self.row_height(row, 30)
            self._row += 1
            self.line(weight=2, pixels=4)
        else:
            self.put(row, FIRST_COL, value)
            self.merge(row, FIRST_COL, row, LAST_COL)
            self.style(row, FIRST_COL, row, LAST_COL, bold=True, size=11,
                       fg=COLOR_INK, align="LEFT", valign="BOTTOM")
            self.row_height(row, 24)
            self._row += 1
        return row

    def kv(self, label: str, value: str, *, label_span: int = 2) -> int:
        row = self._row
        self.put(row, FIRST_COL, label)
        self.style(row, FIRST_COL, row, FIRST_COL + label_span - 1,
                   bold=True, size=10, fg=COLOR_MUTED, align="LEFT", valign="TOP")
        self.put(row, FIRST_COL + label_span, value)
        self.merge(row, FIRST_COL + label_span, row, LAST_COL)
        self.style(row, FIRST_COL + label_span, row, LAST_COL,
                   bold=False, size=10, fg=COLOR_TEXT, align="LEFT", valign="TOP")
        self.row_height(row, 18)
        self._row += 1
        return row

    def paragraph(self, value: str, *, height: int | None = None) -> int:
        row = self._row
        chars_per_line = 95
        lines = max(1, -(-len(value) // chars_per_line))
        self.put(row, FIRST_COL, value)
        self.merge(row, FIRST_COL, row, LAST_COL)
        self.style(row, FIRST_COL, row, LAST_COL, size=10, fg=COLOR_TEXT,
                   align="LEFT", valign="TOP", wrap=True)
        self.row_height(row, height or (16 * lines + 6))
        self._row += 1
        return row

    # ---- table ----------------------------------------------------------- #
    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        spans: Sequence[int] | None = None,
        aligns: Sequence[str] | None = None,
        formats: Sequence[str | None] | None = None,
        zebra: bool = True,
        total_row: Sequence[Any] | None = None,
    ) -> TableInfo:
        n = len(headers)
        spans = list(spans or self._distribute(CONTENT_COLS, n))
        assert sum(spans) == CONTENT_COLS, f"spans {spans} != {CONTENT_COLS}"
        aligns = list(aligns or (["LEFT"] + ["RIGHT"] * (n - 1)))
        formats = list(formats or [None] * n)

        # header -------------------------------------------------------- #
        head_row = self._row
        col = FIRST_COL
        for title, span in zip(headers, spans):
            self.put(head_row, col, title)
            self.merge(head_row, col, head_row, col + span - 1)
            col += span
        self.style(head_row, FIRST_COL, head_row, LAST_COL, bold=True, size=10,
                   fg="FFFFFF", bg=COLOR_HEADER_BG, align="CENTER", valign="MIDDLE")
        self.row_height(head_row, 26)
        self._row += 1

        # body ---------------------------------------------------------- #
        first_body = self._row
        for row_values in rows:
            col = FIRST_COL
            for value, span, fmt in zip(row_values, spans, formats):
                self.put(self._row, col, value)
                if span > 1:
                    self.merge(self._row, col, self._row, col + span - 1)
                col += span
            self.row_height(self._row, 20)
            self._row += 1
        last_body = self._row - 1

        if first_body <= last_body:
            self.style(first_body, FIRST_COL, last_body, LAST_COL, size=10,
                       fg=COLOR_TEXT, valign="MIDDLE")
            for index, (align, fmt) in enumerate(zip(aligns, formats)):
                col = FIRST_COL + sum(spans[:index])
                self.style(first_body, col, last_body, col + spans[index] - 1,
                           align=align, number_format=fmt)
            if zebra:
                for offset, r in enumerate(range(first_body, last_body + 1)):
                    if offset % 2 == 1:
                        self.style(r, FIRST_COL, r, LAST_COL, bg=COLOR_ZEBRA)
            self.borders(first_body, FIRST_COL, last_body, LAST_COL,
                         style="SOLID", color=COLOR_BORDER, width=1)

        # total --------------------------------------------------------- #
        if total_row is not None:
            col = FIRST_COL
            for value, span, fmt in zip(total_row, spans, formats):
                self.put(self._row, col, value)
                if span > 1:
                    self.merge(self._row, col, self._row, col + span - 1)
                col += span
            self.style(self._row, FIRST_COL, self._row, LAST_COL, bold=True, size=10,
                       fg=COLOR_INK, bg=COLOR_TOTAL_BG, valign="MIDDLE")
            for index, (align, fmt) in enumerate(zip(aligns, formats)):
                col = FIRST_COL + sum(spans[:index])
                self.style(self._row, col, self._row, col + spans[index] - 1,
                           align=align, number_format=fmt)
            self.borders(self._row, FIRST_COL, self._row, LAST_COL,
                         style="SOLID_THICK", color=COLOR_LINE, width=2,
                         edges=("TOP", "LEFT", "RIGHT", "BOTTOM"))
            self.row_height(self._row, 24)
            self._row += 1

        return TableInfo(
            header_row=head_row,
            first_body=first_body,
            last_body=last_body,
            total_row=(self._row - 1) if total_row is not None else None,
            spans=spans,
        )

    @staticmethod
    def _distribute(total: int, parts: int) -> list[int]:
        base, rem = divmod(total, parts)
        return [base + (1 if i < rem else 0) for i in range(parts)]

    # ---- signatures / footer -------------------------------------------- #
    def signature(self, pairs: Sequence[tuple[str, str]]) -> int:
        row = self._row
        per = self._distribute(CONTENT_COLS, len(pairs))
        col = FIRST_COL
        for (role, name), width in zip(pairs, per):
            self.put(row, col, role)
            self.merge(row, col, row, col + width - 1)
            self.style(row, col, row, col + width - 1, size=9, fg=COLOR_MUTED)
            self.put(row + 2, col, name)
            self.merge(row + 2, col, row + 2, col + width - 1)
            self.style(row + 2, col, row + 2, col + width - 1, size=10,
                       fg=COLOR_TEXT, align="CENTER")
            self.borders(row + 2, col, row + 2, col + width - 1,
                         style="SOLID", color="808080", width=1, edges=("BOTTOM",))
            self.put(row + 3, col, "подпись")
            self.merge(row + 3, col, row + 3, col + width - 1)
            self.style(row + 3, col, row + 3, col + width - 1, size=8,
                       fg=COLOR_MUTED, align="CENTER")
            col += width
        for r, h in ((row, 16), (row + 1, 14), (row + 2, 20), (row + 3, 14)):
            self.row_height(r, h)
        self._row = row + 4
        return row

    def footer(self, value: str) -> int:
        row = self._row
        self.line(weight=1, color="BFBFBF", pixels=6)
        row = self._row
        self.put(row, FIRST_COL, value)
        self.merge(row, FIRST_COL, row, LAST_COL)
        self.style(row, FIRST_COL, row, LAST_COL, size=8, italic=True,
                   fg=COLOR_MUTED, align="CENTER")
        self.row_height(row, 16)
        self._row += 1
        return row

    # ---- charts ----------------------------------------------------------- #
    def reserve(self, pixels: int, *, step: int = 20) -> int:
        """Block out vertical space for an overlay chart; returns the anchor row."""
        anchor = self._row
        remaining = pixels
        while remaining > 0:
            height = min(step, remaining)
            self.row_height(self._row, height)
            remaining -= height
            self._row += 1
        return anchor

    def chart(
        self,
        *,
        title: str,
        chart_type: str,
        domain: tuple[int, int, int, int],
        series: Sequence[tuple[int, int, int, int]],
        anchor_row: int,
        width: int = 620,
        height: int = 240,
        legend: str = "BOTTOM_LEGEND",
    ) -> None:
        """Overlay a chart built from sheet ranges (ranges include the header row)."""
        spec: dict[str, Any] = {
            "title": title,
            "titleTextFormat": {"bold": True, "fontSize": 11,
                                "foregroundColor": _color(COLOR_INK)},
            "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
            "basicChart": {
                "chartType": chart_type,
                "legendPosition": legend,
                "axis": [{"position": "BOTTOM_AXIS"}, {"position": "LEFT_AXIS"}],
                "domains": [{"domain": {"sourceRange": {"sources": [self._grid_range(*domain)]}}}],
                "series": [
                    {"series": {"sourceRange": {"sources": [self._grid_range(*rng)]}}}
                    for rng in series
                ],
                "headerCount": 1,
            },
        }
        self._requests.append({
            "addChart": {
                "chart": {
                    "spec": spec,
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {
                                "sheetId": self.sheet_id,
                                "rowIndex": anchor_row - 1,
                                "columnIndex": FIRST_COL - 1,
                            },
                            "widthPixels": width,
                            "heightPixels": height,
                        }
                    },
                }
            }
        })

    # ---- build ----------------------------------------------------------- #
    def build(self) -> DocumentSpec:
        rows = self._row
        values: list[list[Any]] = []
        for r in range(1, rows + 1):
            values.append([self._values.get((r, c)) for c in range(1, MARGIN_COL_RIGHT + 1)])
        size_requests = [
            {"updateDimensionProperties": {
                "range": {
                    "sheetId": self.sheet_id,
                    "dimension": "ROWS",
                    "startIndex": r - 1,
                    "endIndex": r,
                },
                "properties": {"pixelSize": h},
                "fields": "pixelSize",
            }}
            for r, h in sorted(self._row_heights.items())
        ]
        return DocumentSpec(
            values=values,
            requests=self._requests + size_requests,
            rows=rows,
        )
