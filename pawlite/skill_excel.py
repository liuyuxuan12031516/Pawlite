from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


def is_excel_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".xlsx", ".xlsm", ".xls"} and not path.name.startswith("~$")


def read_xlsx(
    file_path: Path,
    *,
    max_sheets: int,
    sheet_offset: int,
    max_rows_per_sheet: int,
    row_offset: int,
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(file_path) as archive:
            shared_strings = _read_shared_strings(archive)
            sheets = []
            workbook_sheets = _workbook_sheets(archive)
            selected_sheets = workbook_sheets[sheet_offset : sheet_offset + max_sheets]
            for sheet in selected_sheets:
                rows = _read_sheet_rows(
                    archive,
                    sheet["path"],
                    shared_strings,
                    max_rows=max_rows_per_sheet,
                    row_offset=row_offset,
                )
                sheets.append(
                    {
                        "name": sheet["name"],
                        "rows": rows,
                        "rows_read": len(rows),
                        "row_offset": row_offset,
                        "max_rows": max_rows_per_sheet,
                        "may_have_more_rows": len(rows) >= max_rows_per_sheet,
                    }
                )
            return {
                "ok": True,
                "sheets": sheets,
                "total_sheets": len(workbook_sheets),
                "sheet_offset": sheet_offset,
                "max_sheets": max_sheets,
                "has_more_sheets": sheet_offset + len(selected_sheets) < len(workbook_sheets),
                "next_sheet_offset": sheet_offset + len(selected_sheets)
                if sheet_offset + len(selected_sheets) < len(workbook_sheets)
                else None,
            }
    except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def format_workbook_text(file_name: str, workbook: dict[str, Any]) -> str:
    lines = [f"File: {file_name}"]
    for sheet in workbook.get("sheets", []):
        lines.append(f"Sheet: {sheet.get('name', '')}")
        row_offset = int(sheet.get("row_offset", 0))
        for index, row in enumerate(sheet.get("rows", []), start=1):
            cells = [str(cell) for cell in row]
            lines.append(f"Row {row_offset + index}: " + " | ".join(cells))
    return "\n".join(lines)


def compact_workbook(workbook: dict[str, Any], *, include_rows: bool) -> dict[str, Any]:
    if not workbook.get("ok"):
        return workbook
    compact_sheets = []
    for sheet in workbook.get("sheets", []):
        rows = sheet.get("rows", [])
        compact_sheet = {
            "name": sheet.get("name", ""),
            "rows_read": sheet.get("rows_read", len(rows)),
            "row_offset": sheet.get("row_offset", 0),
            "max_rows": sheet.get("max_rows", len(rows)),
            "may_have_more_rows": sheet.get("may_have_more_rows", False),
            "preview_rows": rows[:2],
        }
        if include_rows:
            compact_sheet["rows"] = rows
        compact_sheets.append(compact_sheet)
    return {
        "ok": True,
        "total_sheets": workbook.get("total_sheets", len(compact_sheets)),
        "sheet_offset": workbook.get("sheet_offset", 0),
        "max_sheets": workbook.get("max_sheets", len(compact_sheets)),
        "has_more_sheets": workbook.get("has_more_sheets", False),
        "next_sheet_offset": workbook.get("next_sheet_offset"),
        "sheets": compact_sheets,
    }


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.findall(".//{*}si"):
        text = "".join(node.text or "" for node in item.findall(".//{*}t"))
        strings.append(text)
    return strings


def _workbook_sheets(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("{*}Relationship")
        if "Id" in rel.attrib and "Target" in rel.attrib
    }

    sheets = []
    for sheet in workbook.findall(".//{*}sheet"):
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rel_id or rel_id not in rel_targets:
            continue
        target = rel_targets[rel_id].lstrip("/")
        sheet_path = target if target.startswith("xl/") else posixpath.normpath(f"xl/{target}")
        sheets.append({"name": sheet.attrib.get("name", rel_id), "path": sheet_path})
    return sheets


def _read_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    max_rows: int,
    row_offset: int,
) -> list[list[str]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: list[list[str]] = []
    seen_non_empty = 0
    for row in root.findall(".//{*}sheetData/{*}row"):
        values = _row_values(row, shared_strings)
        while values and values[-1] == "":
            values.pop()
        if values:
            if seen_non_empty < row_offset:
                seen_non_empty += 1
                continue
            rows.append(values)
            seen_non_empty += 1
        if len(rows) >= max_rows:
            break
    return rows


def _row_values(row: ET.Element, shared_strings: list[str]) -> list[str]:
    values: list[str] = []
    for cell in row.findall("{*}c"):
        ref = cell.attrib.get("r", "")
        column_index = _column_index(ref)
        if column_index is None:
            column_index = len(values)
        while len(values) < column_index:
            values.append("")
        values.append(_cell_value(cell, shared_strings))
    return values


def _column_index(cell_ref: str) -> int | None:
    match = re.match(r"([A-Za-z]+)", cell_ref)
    if not match:
        return None
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t")).strip()

    value_node = cell.find("{*}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text.strip()
    if cell_type == "s":
        try:
            return shared_strings[int(raw)].strip()
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw
