from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .memory import Memory
from .skill_excel import (
    compact_workbook as _compact_workbook,
    format_workbook_text as _format_workbook_text,
    is_excel_file as _is_excel_file,
    read_xlsx as _read_xlsx,
)
from .skill_search import (
    IMAGE_EXTENSIONS,
    is_image_file as _is_image_file,
    normalize_extensions as _normalize_extensions,
    search_file_names as _search_file_names,
)


class SkillError(RuntimeError):
    pass


ActionResult = dict[str, Any]
ESTIMATED_CHARS_PER_TOKEN = 4
READ_FILE_DEFAULT_MAX_TOKENS = 50000


def _json_result(ok: bool, **payload: Any) -> ActionResult:
    return {"ok": ok, **payload}


@dataclass
class SkillContext:
    workspace: Path
    memory: Memory
    require_confirm: bool = True
    vision_complete: Callable[[list[Path], str], str] | None = None
    web_search_complete: Callable[[str, str], str] | None = None

    def resolve_workspace_path(self, path: str) -> Path:
        workspace = self.workspace.resolve()
        candidate = (workspace / path).resolve()
        if not str(candidate).lower().startswith(str(workspace).lower()):
            raise SkillError(f"Path escapes workspace: {path}")
        return candidate

    def resolve_read_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return candidate.resolve()

    def confirm(self, action: str, detail: str) -> bool:
        if not self.require_confirm:
            return True
        answer = input(f"\nAllow {action}? {detail}\nType 'yes' to continue: ").strip().lower()
        return answer == "yes"


class SkillRegistry:
    def __init__(self, context: SkillContext):
        self.context = context
        self._skills: dict[str, Callable[..., ActionResult]] = {
            "list_files": self.list_files,
            "search_files": self.search_files,
            "find_images": self.find_images,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "append_file": self.append_file,
            "describe_image": self.describe_image,
            "web_search": self.web_search,
            "run_shell": self.run_shell,
            "remember": self.remember,
            "search_memory": self.search_memory,
            "now": self.now,
            "read_excel": self.read_excel,
            "read_excel_directory": self.read_excel,
        }

    @property
    def manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "list_files",
                "description": "List files inside the workspace.",
                "args": {"path": "relative directory, default '.'", "max_items": "integer, default 80"},
            },
            {
                "name": "search_files",
                "description": "Search file names under a workspace or explicit read-only absolute directory.",
                "args": {
                    "root": "directory path, default workspace",
                    "query": "file name keywords; common words like file/image/location are ignored",
                    "extensions": "optional list like ['.pdf', '.docx'] or comma string",
                    "max_results": "integer, default 50",
                    "max_depth": "integer, default 8",
                },
            },
            {
                "name": "find_images",
                "description": "Search local image files by file name under a workspace or explicit read-only absolute directory.",
                "args": {
                    "root": "directory path, default workspace",
                    "query": "image name keywords, e.g. 刘亦菲",
                    "max_results": "integer, default 50",
                    "max_depth": "integer, default 8",
                },
            },
            {
                "name": "read_file",
                "description": "Read a UTF-8 text file inside the workspace. Supports offset paging for very large files.",
                "args": {
                    "path": "relative file path",
                    "offset": "character offset, default 0; use next_offset to continue a truncated read",
                    "max_tokens": "approximate token budget, default 50000",
                    "max_chars": "optional exact character budget; overrides max_tokens when provided",
                },
            },
            {
                "name": "write_file",
                "description": "Create or replace a UTF-8 text file inside the workspace.",
                "args": {"path": "relative file path", "content": "file content"},
                "confirmation": "required unless --yes is used",
            },
            {
                "name": "append_file",
                "description": "Append UTF-8 text to a file inside the workspace.",
                "args": {"path": "relative file path", "content": "text to append"},
                "confirmation": "required unless --yes is used",
            },
            {
                "name": "describe_image",
                "description": "Use the configured Qwen multimodal model to inspect one or more local images.",
                "args": {
                    "paths": "image path or list of image paths; explicit read-only absolute paths are allowed",
                    "prompt": "what to inspect or extract from the image",
                    "max_images": "integer, default 4",
                },
            },
            {
                "name": "web_search",
                "description": "Search the web through Qwen search when current or external information is needed.",
                "args": {
                    "query": "specific web search question or keywords",
                    "search_strategy": "optional search strategy, default 'agent'",
                },
            },
            {
                "name": "run_shell",
                "description": "Run a safe shell command in the workspace.",
                "args": {"command": "command string", "timeout": "seconds, default 30"},
                "confirmation": "required unless --yes is used",
            },
            {
                "name": "remember",
                "description": "Persist a note in local memory.",
                "args": {"kind": "short category", "content": "memory content"},
            },
            {
                "name": "search_memory",
                "description": "Search local memory.",
                "args": {"query": "search text", "limit": "integer, default 5"},
            },
            {
                "name": "now",
                "description": "Return current local time.",
                "args": {},
            },
            {
                "name": "read_excel",
                "description": "Parse .xlsx/.xlsm content from a file or directory path, including explicit read-only absolute paths outside the workspace.",
                "args": {
                    "path": "Excel file path or directory path",
                    "max_files": "integer, default 20",
                    "file_offset": "integer, default 0; for directories, skip this many sorted Excel files before reading",
                    "max_sheets": "integer, default 20",
                    "sheet_offset": "integer, default 0; skip this many sheets in each workbook before reading",
                    "max_rows_per_sheet": "integer, default 120",
                    "row_offset": "integer, default 0; skip this many non-empty rows in each selected sheet",
                    "max_chars": "integer, default 20000",
                    "include_rows": "boolean, default false; include raw rows in files metadata",
                },
            },
        ]

    def run(self, name: str, args: dict[str, Any] | None) -> ActionResult:
        if name not in self._skills:
            return _json_result(False, error=f"Unknown skill: {name}")
        try:
            return self._skills[name](**(args or {}))
        except TypeError as exc:
            return _json_result(False, error=f"Bad arguments for {name}: {exc}")
        except SkillError as exc:
            return _json_result(False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - agent tools should report failures as observations.
            return _json_result(False, error=f"{type(exc).__name__}: {exc}")

    def list_files(self, path: str = ".", max_items: int = 80) -> ActionResult:
        root = self.context.resolve_workspace_path(path)
        if not root.exists():
            return _json_result(False, error=f"Path not found: {path}")
        if not root.is_dir():
            return _json_result(False, error=f"Not a directory: {path}")
        items = []
        for child in sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            rel = child.relative_to(self.context.workspace).as_posix()
            items.append({"path": rel, "type": "dir" if child.is_dir() else "file"})
            if len(items) >= int(max_items):
                break
        return _json_result(True, items=items)

    def search_files(
        self,
        root: str = ".",
        query: str = "",
        extensions: str | list[str] | None = None,
        max_results: int = 50,
        max_depth: int = 8,
    ) -> ActionResult:
        search_root = self.context.resolve_read_path(root)
        if not search_root.exists() or not search_root.is_dir():
            return _json_result(False, error=f"Directory not found: {root}")
        normalized_extensions = _normalize_extensions(extensions)
        matches, skipped = _search_file_names(
            search_root,
            query=query,
            extensions=normalized_extensions,
            max_results=max(1, int(max_results)),
            max_depth=max(0, int(max_depth)),
        )
        return _json_result(
            True,
            root=str(search_root),
            query=query,
            extensions=sorted(normalized_extensions) if normalized_extensions else None,
            total_returned=len(matches),
            skipped_dirs=skipped,
            items=matches,
        )

    def find_images(self, root: str = ".", query: str = "", max_results: int = 50, max_depth: int = 8) -> ActionResult:
        return self.search_files(
            root=root,
            query=query,
            extensions=sorted(IMAGE_EXTENSIONS),
            max_results=max_results,
            max_depth=max_depth,
        )

    def read_file(
        self,
        path: str,
        offset: int = 0,
        max_tokens: int = READ_FILE_DEFAULT_MAX_TOKENS,
        max_chars: int | None = None,
    ) -> ActionResult:
        file_path = self.context.resolve_workspace_path(path)
        if not file_path.exists() or not file_path.is_file():
            return _json_result(False, error=f"File not found: {path}")
        data = file_path.read_text(encoding="utf-8", errors="replace")
        start = max(0, int(offset))
        limit = int(max_chars) if max_chars is not None else max(1, int(max_tokens)) * ESTIMATED_CHARS_PER_TOKEN
        end = min(len(data), start + max(1, limit))
        truncated = end < len(data)
        next_offset = end if truncated else None
        return _json_result(
            True,
            path=file_path.relative_to(self.context.workspace.resolve()).as_posix(),
            content=data[start:end],
            offset=start,
            next_offset=next_offset,
            total_chars=len(data),
            max_tokens=int(max_tokens),
            max_chars=max(1, limit),
            approx_tokens=max(1, (end - start + ESTIMATED_CHARS_PER_TOKEN - 1) // ESTIMATED_CHARS_PER_TOKEN),
            truncated=truncated,
            note=(
                f"Content truncated. Continue with read_file(path={path!r}, offset={next_offset}) "
                "to read the next chunk."
                if truncated
                else "Full file content returned."
            ),
        )

    def write_file(self, path: str, content: str) -> ActionResult:
        return self._save_text_file("write_file", path, content, append=False)

    def append_file(self, path: str, content: str) -> ActionResult:
        return self._save_text_file("append_file", path, content, append=True)

    def _save_text_file(self, action: str, path: str, content: str, *, append: bool) -> ActionResult:
        file_path = self.context.resolve_workspace_path(path)
        if self._reject_raw_work_dump(file_path, content):
            return _json_result(False, error=f"Refusing to {action} raw tool output under .pawlite_work; write compact extracted notes instead.")
        if not self.context.confirm(action, path):
            return _json_result(False, error=f"User denied {action}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with file_path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            file_path.write_text(content, encoding="utf-8")
        return _json_result(True, path=file_path.relative_to(self.context.workspace).as_posix(), bytes=len(content.encode("utf-8")))

    def describe_image(self, paths: str | list[str], prompt: str = "Describe the image.", max_images: int = 4) -> ActionResult:
        if self.context.vision_complete is None:
            return _json_result(False, error="Vision model is not configured.")
        raw_paths = [paths] if isinstance(paths, str) else list(paths)
        image_paths = []
        for raw_path in raw_paths[: max(1, int(max_images))]:
            image_path = self.context.resolve_read_path(str(raw_path))
            if not image_path.exists() or not image_path.is_file():
                return _json_result(False, error=f"Image not found: {raw_path}")
            if not _is_image_file(image_path):
                return _json_result(False, error=f"Unsupported image type: {raw_path}")
            image_paths.append(image_path)
        if not image_paths:
            return _json_result(False, error="No image paths were provided.")
        description = self.context.vision_complete(image_paths, prompt)
        return _json_result(True, paths=[str(path) for path in image_paths], description=description)

    def web_search(self, query: str, search_strategy: str = "agent") -> ActionResult:
        if self.context.web_search_complete is None:
            return _json_result(False, error="Web search is not configured.")
        text = self.context.web_search_complete(query, search_strategy)
        return _json_result(True, query=query, search_strategy=search_strategy, content=text)

    def run_shell(self, command: str, timeout: int = 30) -> ActionResult:
        denied = self._dangerous_command_reason(command)
        if denied:
            return _json_result(False, error=denied)
        if not self.context.confirm("run_shell", command):
            return _json_result(False, error="User denied run_shell")
        proc = subprocess.run(
            command,
            cwd=self.context.workspace,
            shell=True,
            text=True,
            capture_output=True,
            timeout=int(timeout),
        )
        return _json_result(
            proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-8000:],
        )

    def remember(self, kind: str, content: str) -> ActionResult:
        return _json_result(True, item=self.context.memory.add(kind, content))

    def search_memory(self, query: str, limit: int = 5) -> ActionResult:
        return _json_result(True, items=self.context.memory.search(query, int(limit)))

    def now(self) -> ActionResult:
        return _json_result(True, time=datetime.now().isoformat(timespec="seconds"), cwd=os.getcwd())

    def read_excel(
        self,
        path: str,
        max_files: int = 20,
        file_offset: int = 0,
        max_sheets: int = 20,
        sheet_offset: int = 0,
        max_rows_per_sheet: int = 120,
        row_offset: int = 0,
        max_chars: int = 20000,
        include_rows: bool = False,
    ) -> ActionResult:
        source = self.context.resolve_read_path(path)
        if not source.exists():
            return _json_result(False, error=f"Path not found: {path}")

        if source.is_dir():
            root = source
            all_excel_files = [
                item
                for item in sorted(root.rglob("*"), key=lambda file: file.relative_to(root).as_posix().lower())
                if _is_excel_file(item)
            ]
            source_type = "directory"
        elif source.is_file():
            root = source.parent
            all_excel_files = [source] if _is_excel_file(source) else []
            source_type = "file"
        else:
            return _json_result(False, error=f"Not a file or directory: {path}")

        total_files = len(all_excel_files)
        offset = max(0, int(file_offset))
        limit = 1 if source_type == "file" else max(1, int(max_files))
        excel_files = all_excel_files[offset : offset + limit]
        if not excel_files:
            return _json_result(
                True,
                path=str(source),
                source_type=source_type,
                total_files=total_files,
                file_offset=offset,
                max_files=limit,
                files=[],
                content="",
                truncated=False,
                has_more=False,
                next_file_offset=None,
            )

        files: list[dict[str, Any]] = []
        content_parts: list[str] = []
        unsupported: list[str] = []

        for file_path in excel_files:
            rel_name = file_path.relative_to(root).as_posix()
            if file_path.suffix.lower() == ".xls":
                unsupported.append(rel_name)
                files.append({"path": rel_name, "ok": False, "error": "Legacy .xls is not supported without extra dependencies."})
                continue
            workbook = _read_xlsx(
                file_path,
                max_sheets=max(1, int(max_sheets)),
                sheet_offset=max(0, int(sheet_offset)),
                max_rows_per_sheet=max(1, int(max_rows_per_sheet)),
                row_offset=max(0, int(row_offset)),
            )
            files.append({"path": rel_name, **_compact_workbook(workbook, include_rows=bool(include_rows))})
            if workbook.get("ok"):
                content_parts.append(_format_workbook_text(rel_name, workbook))

        content = "\n\n".join(part for part in content_parts if part)
        truncated = len(content) > int(max_chars)
        return _json_result(
            True,
            path=str(source),
            source_type=source_type,
            total_files=total_files,
            file_offset=offset,
            max_files=limit,
            sheet_offset=max(0, int(sheet_offset)),
            max_sheets=max(1, int(max_sheets)),
            row_offset=max(0, int(row_offset)),
            max_rows_per_sheet=max(1, int(max_rows_per_sheet)),
            has_more=offset + len(excel_files) < total_files,
            next_file_offset=offset + len(excel_files) if offset + len(excel_files) < total_files else None,
            files=files,
            unsupported=unsupported,
            content=content[: int(max_chars)],
            truncated=truncated,
        )

    @staticmethod
    def _dangerous_command_reason(command: str) -> str | None:
        lowered = command.lower()
        patterns = [
            r"\brm\s+-rf\b",
            r"\bdel\s+/[fsq]\b",
            r"\brmdir\s+/s\b",
            r"\bformat\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-fd\b",
            r"\bshutdown\b",
            r"\brestart-computer\b",
        ]
        if any(re.search(pattern, lowered) for pattern in patterns):
            return "Command rejected by safety policy"
        return None

    def _reject_raw_work_dump(self, file_path: Path, content: str) -> bool:
        try:
            rel_path = file_path.relative_to(self.context.workspace).as_posix().lower()
        except ValueError:
            rel_path = file_path.as_posix().lower()
        if not rel_path.startswith(".pawlite_work/"):
            return False

        stripped = content.strip()
        lowered = stripped.lower()
        if "raw" in posixpath.basename(rel_path):
            return True
        if '"tool": "read_excel"' in lowered or '"tool":"read_excel"' in lowered:
            return True
        if '"preview_rows"' in lowered and '"source_type"' in lowered:
            return True
        if stripped.startswith("{") and '"files"' in lowered and '"content"' in lowered and '"row_offset"' in lowered:
            return True
        return bool(
            len(content) > 4000
            and "file:" in lowered
            and "sheet:" in lowered
            and len(re.findall(r"\brow\s+\d+:", lowered)) >= 5
        )


def format_observation(tool: str, args: dict[str, Any], result: ActionResult) -> str:
    return json.dumps({"tool": tool, "args": args, "result": result}, ensure_ascii=False)
