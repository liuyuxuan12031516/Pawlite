from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
}
GENERIC_SEARCH_WORDS = {
    "file",
    "files",
    "find",
    "image",
    "images",
    "location",
    "photo",
    "photos",
    "picture",
    "pictures",
    "search",
    "位置",
    "图片",
    "照片",
    "文件",
    "查找",
    "找到",
    "所在",
}


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def normalize_extensions(extensions: str | list[str] | None) -> set[str] | None:
    if extensions is None:
        return None
    values: Iterable[str]
    if isinstance(extensions, str):
        values = re.split(r"[,;\s]+", extensions)
    else:
        values = extensions
    normalized = {value.lower() if value.startswith(".") else f".{value.lower()}" for value in values if value}
    return normalized or None


def search_file_names(
    root: Path,
    *,
    query: str,
    extensions: set[str] | None,
    max_results: int,
    max_depth: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    tokens = _search_tokens(query)
    matches: list[dict[str, Any]] = []
    skipped_dirs: list[str] = []
    root = root.resolve()

    for current_root, dir_names, file_names in os.walk(root, topdown=True):
        current = Path(current_root)
        try:
            rel_dir = current.relative_to(root)
        except ValueError:
            rel_dir = Path()
        depth = 0 if rel_dir == Path(".") else len(rel_dir.parts)
        if depth >= max_depth:
            skipped_dirs.extend(str(current / name) for name in dir_names[:20])
            dir_names[:] = []
        else:
            dir_names[:] = [
                name
                for name in dir_names
                if name not in DEFAULT_SKIP_DIRS and not name.startswith("$")
            ]

        for file_name in sorted(file_names, key=str.lower):
            path = current / file_name
            suffix = path.suffix.lower()
            if extensions is not None and suffix not in extensions:
                continue
            haystack = f"{file_name} {path.as_posix()}".lower()
            if tokens and not all(token in haystack for token in tokens):
                continue
            matches.append(_file_match_record(path))
            if len(matches) >= max_results:
                return matches, skipped_dirs[:50]
    return matches, skipped_dirs[:50]


def _search_tokens(query: str) -> list[str]:
    tokens = [token.lower() for token in re.split(r"[\s,;，；]+", query) if token.strip()]
    specific_tokens = [token for token in tokens if token not in GENERIC_SEARCH_WORDS]
    return specific_tokens or tokens


def _file_match_record(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        size = stat.st_size
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except OSError:
        size = None
        modified = None
    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "size": size,
        "modified": modified,
    }
