from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_VLM_MODEL = "qwen3.6-plus"
DEFAULT_LANGUAGE = "简体中文"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str
    language: str
    workspace: Path
    memory_path: Path
    require_confirm: bool = True
    offline: bool = False
    max_steps: int = 6
    stream: bool = True

    @classmethod
    def from_env(
        cls,
        workspace: Path,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        language: str | None = None,
        yes: bool = False,
        offline: bool = False,
        max_steps: int = 6,
        stream: bool = True,
    ) -> "Config":
        load_dotenv(workspace / ".env")
        key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("QWEN_API_KEY")
            or os.getenv("MODELSTUDIO_API_KEY")
            or os.getenv("API_KEY")
            or ""
        )
        return cls(
            base_url=(base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            model=model or os.getenv("DASHSCOPE_MODEL") or DEFAULT_VLM_MODEL,
            api_key=key,
            language=language or os.getenv("PAWLITE_LANGUAGE") or os.getenv("OPENCLAW_LANGUAGE") or os.getenv("OUTPUT_LANGUAGE") or DEFAULT_LANGUAGE,
            workspace=workspace.resolve(),
            memory_path=workspace.resolve() / ".pawlite_memory.json",
            require_confirm=not yes,
            offline=offline,
            max_steps=max_steps,
            stream=stream,
        )
