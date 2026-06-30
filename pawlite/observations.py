from __future__ import annotations

import json
from typing import Any


OLD_OBSERVATION_MAX_CHARS = 4000
RECENT_OBSERVATIONS_TO_KEEP = 1
RESULT_METADATA_KEYS = (
    "path",
    "source_type",
    "total_files",
    "file_offset",
    "max_files",
    "offset",
    "next_offset",
    "total_chars",
    "max_tokens",
    "max_chars",
    "approx_tokens",
    "has_more",
    "next_file_offset",
    "truncated",
    "note",
    "unsupported",
    "output_path",
    "work_dir",
    "bytes",
    "exit_code",
)
RESULT_SUMMARY_KEYS = (
    "error",
    *RESULT_METADATA_KEYS,
    "sheet_offset",
    "max_sheets",
    "row_offset",
    "max_rows_per_sheet",
    "root",
    "query",
    "total_returned",
)
COMPACT_OBSERVATION_KEYS = RESULT_METADATA_KEYS


def summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for key, value in args.items():
        if key in {"content"}:
            summarized[key] = f"<{len(str(value))} chars>"
        elif isinstance(value, str) and len(value) > 200:
            summarized[key] = value[:200] + "...<truncated>"
        else:
            summarized[key] = value
    return summarized


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"ok": result.get("ok")}
    for key in RESULT_SUMMARY_KEYS:
        if key in result:
            summary[key] = result[key]
    if "content" in result:
        summary["content"] = f"<{len(str(result.get('content', '')))} chars omitted>"
    if "stdout" in result:
        summary["stdout"] = f"<{len(str(result.get('stdout', '')))} chars omitted>"
    if "stderr" in result:
        summary["stderr"] = f"<{len(str(result.get('stderr', '')))} chars omitted>"
    if "description" in result:
        summary["description"] = str(result["description"])[:2000]
    if "files" in result and isinstance(result["files"], list):
        summary["files"] = [
            summarize_file_result(file_item)
            for file_item in result["files"][:20]
            if isinstance(file_item, dict)
        ]
        if len(result["files"]) > 20:
            summary["files_omitted"] = len(result["files"]) - 20
    if "items" in result and isinstance(result["items"], list):
        summary["items"] = result["items"][:40]
        if len(result["items"]) > 40:
            summary["items_omitted"] = len(result["items"]) - 40
    return summary


def summarize_file_result(file_item: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for key in ("path", "ok", "error", "total_sheets", "sheet_offset", "max_sheets", "has_more_sheets", "next_sheet_offset"):
        if key in file_item:
            summarized[key] = file_item[key]
    if "sheets" in file_item and isinstance(file_item["sheets"], list):
        summarized["sheets"] = [
            {
                "name": sheet.get("name"),
                "rows_read": sheet.get("rows_read"),
                "row_offset": sheet.get("row_offset"),
                "max_rows": sheet.get("max_rows"),
                "may_have_more_rows": sheet.get("may_have_more_rows"),
            }
            for sheet in file_item["sheets"][:20]
            if isinstance(sheet, dict)
        ]
    return summarized


def compact_old_observations(messages: list[dict[str, str]]) -> None:
    observation_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content", "").startswith("Observations:\n")
    ]
    for index in observation_indexes[:-RECENT_OBSERVATIONS_TO_KEEP]:
        content = messages[index].get("content", "")
        if len(content) <= OLD_OBSERVATION_MAX_CHARS or content.startswith("Observations compacted"):
            continue
        messages[index]["content"] = compact_observation_message(content)


def compact_observation_message(content: str) -> str:
    summaries: list[dict[str, Any]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        summary: dict[str, Any] = {
            "tool": item.get("tool"),
            "args": item.get("args", {}),
            "ok": result.get("ok"),
        }
        for key in COMPACT_OBSERVATION_KEYS:
            if key in result:
                summary[key] = result[key]
        if "files" in result and isinstance(result["files"], list):
            summary["files"] = [
                {
                    "path": file_item.get("path"),
                    "ok": file_item.get("ok"),
                    "total_sheets": file_item.get("total_sheets"),
                    "sheet_offset": file_item.get("sheet_offset"),
                    "has_more_sheets": file_item.get("has_more_sheets"),
                }
                for file_item in result["files"][:20]
                if isinstance(file_item, dict)
            ]
        summaries.append(summary)
    return "Observations compacted; raw content omitted after it was available to the previous model step:\n" + json.dumps(
        summaries,
        ensure_ascii=False,
    )
