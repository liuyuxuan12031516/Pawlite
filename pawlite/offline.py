from __future__ import annotations

import re
from typing import Any, Callable


def run_offline_demo(task: str, skills: Any, event_factory: Callable[[str, dict[str, Any]], Any]) -> list[Any]:
    events = []
    lower = task.lower()
    filename = extract_filename(task) or "demo_output.txt"

    if any(word in lower for word in ["列出", "list", "目录", "files"]):
        result = skills.run("list_files", {"path": "."})
        events.append(event_factory("action", {"tool": "list_files", "args": {"path": "."}, "result": result, "reason": "offline demo list"}))
        events.append(event_factory("final", {"message": "已列出当前工作区文件。"}))
        return events

    content = extract_content(task) or "Hello from Pawlite.\n"
    result = skills.run("write_file", {"path": filename, "content": content})
    events.append(event_factory("action", {"tool": "write_file", "args": {"path": filename, "content": content}, "result": result, "reason": "offline demo write"}))
    events.append(event_factory("final", {"message": f"离线 demo 已尝试写入 {filename}。"}))
    return events


def extract_filename(task: str) -> str | None:
    patterns = [
        r"([\w./\\-]+\.(?:txt|md|json|py|csv|log))",
        r"文件\s*([\w./\\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, task, flags=re.I)
        if match:
            return match.group(1).replace("\\", "/")
    return None


def extract_content(task: str) -> str | None:
    match = re.search(r"(?:写入|内容是|content is)\s*[:：]?\s*(.+)$", task, flags=re.I | re.S)
    if match:
        return match.group(1).strip() + "\n"
    return None
