from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Memory:
    path: Path

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items[-200:], ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, kind: str, content: str) -> dict[str, Any]:
        items = self._load()
        item = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "content": content,
        }
        items.append(item)
        self._save(items)
        return item

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_lower = query.lower()
        hits = [
            item
            for item in reversed(self._load())
            if query_lower in str(item.get("content", "")).lower()
            or query_lower in str(item.get("kind", "")).lower()
        ]
        return hits[:limit]

    def recent(self, limit: int = 8) -> list[dict[str, Any]]:
        return list(reversed(self._load()))[:limit]
