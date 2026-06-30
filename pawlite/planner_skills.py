from __future__ import annotations

import re
from pathlib import Path


PLANNER_SKILL_DESCRIPTION_MAX_CHARS = 500


class PlannerSkillStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._catalog: list[dict[str, str]] | None = None

    def catalog(self) -> list[dict[str, str]]:
        if self._catalog is None:
            self._catalog = self._load_catalog()
        return list(self._catalog)

    def read_report(self, name: str) -> dict[str, object]:
        doc = self.read(name)
        if doc.get("ok") != "true":
            error = doc.get("error", "Planner skill could not be read.")
            return {
                "task_title": f"Read skill: {name or 'unknown'}",
                "status": "blocked",
                "summary": error,
                "artifacts": [],
                "coverage": [],
                "limitations": [doc.get("error", "Planner skill not found.")],
                "suggested_next_steps": [],
            }

        return {
            "task_title": f"Read skill: {doc['name']}",
            "status": "completed",
            "summary": f"Read external planner skill {doc['name']} from {doc['path']}.",
            "artifacts": [doc["path"]],
            "coverage": [f"Full SKILL.md content loaded for {doc['name']}."],
            "limitations": [],
            "suggested_next_steps": [],
            "content": doc["content"],
        }

    def read(self, name: str) -> dict[str, str]:
        for item in self.catalog():
            if name not in {item["name"], Path(item["path"]).parent.name}:
                continue
            skill_file = (self.workspace / item["path"]).resolve()
            try:
                content = skill_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return {"name": name, "ok": "false", "error": str(exc)}
            return {
                "name": item["name"],
                "ok": "true",
                "path": item["path"],
                "content": content,
            }
        return {"name": name, "ok": "false", "error": "Planner skill not found in skills/*/SKILL.md."}

    def _load_catalog(self) -> list[dict[str, str]]:
        skills_root = (self.workspace / "skills").resolve()
        if not skills_root.is_dir():
            return []

        catalog: list[dict[str, str]] = []
        for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                header = skill_file.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            metadata = parse_skill_frontmatter(header)
            name = metadata.get("name") or skill_dir.name
            description = metadata.get("description", "")
            catalog.append(
                {
                    "name": name[:120],
                    "description": description[:PLANNER_SKILL_DESCRIPTION_MAX_CHARS],
                    "path": workspace_relative_path(self.workspace, skill_file),
                }
            )
        return catalog


def parse_skill_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"---\s*\n(.*?)\n---", text, flags=re.S)
    if not match:
        return {}

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"name", "description"}:
            metadata[key] = value.strip().strip("\"'")
    return metadata


def workspace_relative_path(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace).as_posix()
    except ValueError:
        return path.name
