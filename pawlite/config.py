from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_VLM_MODEL = "qwen3.6-plus"
DEFAULT_LANGUAGE = "简体中文"


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _first_nonempty(*values: str | None) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _lookup_env(key: str) -> str:
    value = os.getenv(key)
    if value and value.strip():
        return value.strip()
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    reg_paths = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    for hive, subkey in reg_paths:
        try:
            with winreg.OpenKey(hive, subkey) as reg_key:
                raw, _ = winreg.QueryValueEx(reg_key, key)
        except OSError:
            continue
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, (int, float)):
            return str(raw)
    return ""


def _resolve(
    *,
    cli_value: str | None,
    dotenv: dict[str, str],
    env_keys: tuple[str, ...],
    default: str = "",
) -> str:
    candidates: list[str | None] = []
    if cli_value is not None:
        candidates.append(cli_value)
    for key in env_keys:
        candidates.append(dotenv.get(key))
        candidates.append(_lookup_env(key))
    candidates.append(default or None)
    return _first_nonempty(*candidates)


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
        dotenv = read_dotenv(workspace / ".env")
        key = _resolve(
            cli_value=api_key,
            dotenv=dotenv,
            env_keys=("DASHSCOPE_API_KEY", "QWEN_API_KEY", "MODELSTUDIO_API_KEY", "API_KEY"),
        )
        return cls(
            base_url=_resolve(
                cli_value=base_url,
                dotenv=dotenv,
                env_keys=("DASHSCOPE_BASE_URL",),
                default=DEFAULT_BASE_URL,
            ).rstrip("/"),
            model=_resolve(
                cli_value=model,
                dotenv=dotenv,
                env_keys=("DASHSCOPE_MODEL",),
                default=DEFAULT_VLM_MODEL,
            ),
            api_key=key,
            language=_resolve(
                cli_value=language,
                dotenv=dotenv,
                env_keys=("PAWLITE_LANGUAGE", "OPENCLAW_LANGUAGE", "OUTPUT_LANGUAGE"),
                default=DEFAULT_LANGUAGE,
            ),
            workspace=workspace.resolve(),
            memory_path=workspace.resolve() / ".pawlite_memory.json",
            require_confirm=not yes,
            offline=offline,
            max_steps=max_steps,
            stream=stream,
        )
