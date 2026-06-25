from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import PawliteAgent
from .config import Config, DEFAULT_LANGUAGE


REASONING_MAX_CHARS = 500
THOUGHT_MAX_CHARS = 160


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pawlite: lightweight local personal agent powered by Qwen.")
    parser.add_argument("task", nargs="*", help="Task for the agent. Omit to enter interactive mode.")
    parser.add_argument("--workspace", default=".", help="Workspace directory the agent can operate in.")
    parser.add_argument("--base-url", default=None, help="API base URL. Default from DASHSCOPE_BASE_URL in .env.")
    parser.add_argument("--model", default=None, help="Model name. Default from DASHSCOPE_MODEL in .env.")
    parser.add_argument("--api-key", default=None, help="API key. Default from DASHSCOPE_API_KEY in .env or system env.")
    parser.add_argument("--language", default=None, help=f"Reasoning/output language. Default: {DEFAULT_LANGUAGE}")
    parser.add_argument("--yes", action="store_true", help="Auto-approve write_file/append_file/run_shell actions.")
    parser.add_argument("--offline", action="store_true", help="Use a tiny local planner for smoke tests without API calls.")
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum sense-think-act iterations.")
    parser.add_argument("--json", action="store_true", help="Print raw event JSON lines.")
    parser.add_argument("--verbose", action="store_true", help="Show full reasoning, model input/output, and tool args.")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming model output.")
    parser.add_argument("--image", action="append", default=[], help="Attach a local image path for multimodal tasks. Repeat for multiple images.")
    parser.add_argument("--version", action="version", version=f"pawlite {__version__}")
    return parser


def main() -> int:
    _configure_console_encoding()
    args = build_parser().parse_args()
    workspace = Path(args.workspace).resolve()
    config = Config.from_env(
        workspace,
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        language=args.language,
        yes=args.yes,
        offline=args.offline,
        max_steps=args.max_steps,
        stream=not args.no_stream,
    )
    agent = PawliteAgent(config)

    if args.task:
        task = " ".join(args.task)
        if args.image:
            task += "\n\nAttached local images:\n" + "\n".join(f"- {path}" for path in args.image)
            task += "\nUse describe_image when visual inspection is needed."
        _print_event_stream(agent.run_task_stream(task), raw_json=args.json, verbose=args.verbose)
        return 0

    print("Pawlite interactive shell. Type 'exit' to quit.")
    while True:
        try:
            task = input("\npawlite> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if task.lower() in {"exit", "quit", "q"}:
            return 0
        if not task:
            continue
        _print_event_stream(agent.run_task_stream(task), raw_json=args.json, verbose=args.verbose)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _format_tool_line(tool: str, args: dict) -> str:
    if not args:
        return tool
    if tool == "read_file":
        suffix = f"@{args.get('offset')}" if args.get("offset") else ""
        return f"{tool}({args.get('path', '')}{suffix})"
    if tool in {"write_file", "append_file"}:
        return f"{tool}({args.get('path', '')})"
    if tool == "list_files":
        return f"{tool}({args.get('path', '.')})"
    if tool in {"search_files", "find_images", "read_excel", "read_excel_directory"}:
        return f"{tool}({args.get('path') or args.get('root', '')})"
    if tool == "describe_image":
        paths = args.get("paths")
        if isinstance(paths, list):
            return f"{tool}({', '.join(str(p) for p in paths[:2])})"
        return f"{tool}({paths})"
    if tool == "run_shell":
        command = str(args.get("command", ""))
        return f"{tool}({command[:80]}{'...' if len(command) > 80 else ''})"
    if tool == "remember":
        return f"{tool}({args.get('kind', '')})"
    return f"{tool}({', '.join(f'{k}={v!r}' for k, v in list(args.items())[:3])})"


def _thought_from_parsed(parsed: object) -> str | None:
    if isinstance(parsed, dict):
        thought = parsed.get("thought")
        if isinstance(thought, str) and thought.strip():
            return _short_text(thought.strip(), THOUGHT_MAX_CHARS)
    return None


def _short_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "...<省略>"


def _print_role_divider(label: str, detail: str | None = None) -> None:
    suffix = f" {detail}" if detail else ""
    print(f"\n······ {label}{suffix} ······", flush=True)


def _print_event_stream(events, *, raw_json: bool = False, verbose: bool = False) -> None:
    streaming_role: str | None = None
    streaming_segment: str | None = None
    streaming_had_reasoning = False
    streaming_reasoning_chars = 0
    for event in events:
        if raw_json:
            print(json.dumps({"kind": event.kind, **event.payload}, ensure_ascii=False), flush=True)
            continue
        if event.kind == "planner_start":
            streaming_role = "planner"
            streaming_segment = None
            streaming_had_reasoning = False
            streaming_reasoning_chars = 0
            _print_role_divider("Planner", f"step {event.payload['step']}")
        elif event.kind == "planner_delta":
            streaming_segment, streaming_had_reasoning, streaming_reasoning_chars = _print_stream_delta(
                event,
                streaming_segment=streaming_segment,
                streaming_had_reasoning=streaming_had_reasoning,
                streaming_reasoning_chars=streaming_reasoning_chars,
                verbose=verbose,
            )
        elif event.kind == "planner":
            if streaming_role == "planner":
                print(flush=True)
            if not streaming_had_reasoning:
                thought = _thought_from_parsed(event.payload.get("parsed"))
                if thought:
                    print(f"  {thought}", flush=True)
            streaming_role = None
            streaming_segment = None
            streaming_had_reasoning = False
            streaming_reasoning_chars = 0
        elif event.kind == "executor_start":
            title = event.payload.get("title") or "subtask"
            _print_role_divider("Executor", str(title))
        elif event.kind == "executor_model_start":
            streaming_role = "executor"
            streaming_segment = None
            streaming_had_reasoning = False
            streaming_reasoning_chars = 0
        elif event.kind == "executor_delta":
            streaming_segment, streaming_had_reasoning, streaming_reasoning_chars = _print_stream_delta(
                event,
                streaming_segment=streaming_segment,
                streaming_had_reasoning=streaming_had_reasoning,
                streaming_reasoning_chars=streaming_reasoning_chars,
                verbose=verbose,
            )
        elif event.kind == "executor_model":
            if streaming_role == "executor":
                print(flush=True)
            if not streaming_had_reasoning:
                thought = _thought_from_parsed(event.payload.get("parsed"))
                if thought:
                    print(f"  {thought}", flush=True)
            streaming_role = None
            streaming_segment = None
            streaming_had_reasoning = False
            streaming_reasoning_chars = 0
        elif event.kind == "executor_action":
            tool = event.payload["tool"]
            args = event.payload.get("args") or {}
            print(f"· tool: {_format_tool_line(tool, args)}", flush=True)
            if verbose:
                _print_verbose_json("tool JSON", event.payload)
        elif event.kind == "executor_finish":
            report = event.payload.get("report") or {}
            summary = report.get("summary", "")
            if summary:
                print(f"· done: {summary}", flush=True)
        elif event.kind == "model_input":
            continue
        elif event.kind == "model_output":
            if verbose:
                actor = event.payload.get("actor", "model")
                content = event.payload.get("content") or ""
                label = "Planner output JSON" if actor == "planner" else "Executor output JSON"
                print(f"\n[verbose] {label}:\n{content}", flush=True)
        elif event.kind == "action":
            tool = event.payload["tool"]
            args = event.payload.get("args") or {}
            print(f"\n[action] {_format_tool_line(tool, args)}", flush=True)
        elif event.kind == "error":
            print(f"\n[error] {event.payload['message']}")
        elif event.kind == "final":
            print(f"\n【结果】\n{event.payload['message']}")


def _print_stream_delta(
    event: AgentEvent,
    *,
    streaming_segment: str | None,
    streaming_had_reasoning: bool,
    streaming_reasoning_chars: int,
    verbose: bool = False,
) -> tuple[str | None, bool, int]:
    reasoning = event.payload.get("reasoning") or ""
    if reasoning:
        if streaming_segment != "reasoning":
            print(f"· reasoning: ", end="", flush=True)
            streaming_segment = "reasoning"
        if verbose:
            print(reasoning, end="", flush=True)
            streaming_reasoning_chars += len(reasoning)
        else:
            remaining = REASONING_MAX_CHARS - streaming_reasoning_chars
            if remaining > 0:
                visible = reasoning[:remaining]
                print(visible, end="", flush=True)
                streaming_reasoning_chars += len(visible)
                if len(reasoning) > remaining:
                    print("...<省略>", end="", flush=True)
                    streaming_reasoning_chars = REASONING_MAX_CHARS
        streaming_had_reasoning = True
    return streaming_segment, streaming_had_reasoning, streaming_reasoning_chars


def _print_verbose_json(label: str, payload: object) -> None:
    print(f"\n[verbose] {label}:", flush=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
