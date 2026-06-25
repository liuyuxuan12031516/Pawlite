from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import AgentEvent, PawliteAgent
from .config import Config, DEFAULT_BASE_URL, DEFAULT_LANGUAGE, DEFAULT_VLM_MODEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pawlite: lightweight local personal agent powered by Qwen.")
    parser.add_argument("task", nargs="*", help="Task for the agent. Omit to enter interactive mode.")
    parser.add_argument("--workspace", default=".", help="Workspace directory the agent can operate in.")
    parser.add_argument("--base-url", default=None, help=f"DashScope/Qwen base URL. Default: {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default=None, help=f"Model name. Default: {DEFAULT_VLM_MODEL}")
    parser.add_argument("--api-key", default=None, help="API key. Prefer DASHSCOPE_API_KEY/QWEN_API_KEY or .env.")
    parser.add_argument("--language", default=None, help=f"Reasoning/output language. Default: {DEFAULT_LANGUAGE}")
    parser.add_argument("--yes", action="store_true", help="Auto-approve write_file/append_file/run_shell actions.")
    parser.add_argument("--offline", action="store_true", help="Use a tiny local planner for smoke tests without API calls.")
    parser.add_argument("--max-steps", type=int, default=6, help="Maximum sense-think-act iterations.")
    parser.add_argument("--json", action="store_true", help="Print raw event JSON lines.")
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
        _print_event_stream(agent.run_task_stream(task), raw_json=args.json)
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
        _print_event_stream(agent.run_task_stream(task), raw_json=args.json)


def _print_events(events: list[AgentEvent], *, raw_json: bool = False) -> None:
    _print_event_stream(iter(events), raw_json=raw_json)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _print_event_stream(events, *, raw_json: bool = False) -> None:
    streaming_role: str | None = None
    streaming_segment: str | None = None
    streaming_had_reasoning = False
    for event in events:
        if raw_json:
            print(json.dumps({"kind": event.kind, **event.payload}, ensure_ascii=False), flush=True)
            continue
        if event.kind == "planner_start":
            streaming_role = "planner"
            streaming_segment = None
            streaming_had_reasoning = False
            print(f"\n[planner step {event.payload['step']}]", flush=True)
        elif event.kind == "planner_delta":
            streaming_segment, streaming_had_reasoning = _print_stream_delta(
                event,
                role="planner",
                streaming_segment=streaming_segment,
                streaming_had_reasoning=streaming_had_reasoning,
            )
        elif event.kind == "planner":
            if streaming_role == "planner":
                print(flush=True)
                streaming_role = None
                streaming_segment = None
                streaming_had_reasoning = False
        elif event.kind == "executor_start":
            title = event.payload.get("title") or "subtask"
            reason = event.payload.get("reason") or ""
            suffix = f" - {reason}" if reason else ""
            print(f"\n[executor] start: {title}{suffix}", flush=True)
        elif event.kind == "executor_model_start":
            streaming_role = "executor"
            streaming_segment = None
            streaming_had_reasoning = False
            print(f"[executor step {event.payload['executor_step']}]", flush=True)
        elif event.kind == "executor_delta":
            streaming_segment, streaming_had_reasoning = _print_stream_delta(
                event,
                role="executor",
                streaming_segment=streaming_segment,
                streaming_had_reasoning=streaming_had_reasoning,
            )
        elif event.kind == "executor_model":
            if streaming_role == "executor":
                print(flush=True)
                streaming_role = None
                streaming_segment = None
                streaming_had_reasoning = False
        elif event.kind == "executor_action":
            tool = event.payload["tool"]
            reason = event.payload.get("reason") or ""
            args = event.payload.get("args") or {}
            suffix = f" - {reason}" if reason else ""
            print(f"[tool] {tool}{suffix}")
            if args:
                print(f"[tool args] {json.dumps(args, ensure_ascii=False)}")
        elif event.kind == "executor_finish":
            report = event.payload.get("report") or {}
            status = report.get("status", "unknown")
            summary = report.get("summary", "")
            print(f"[executor] finish: {status} - {summary}", flush=True)
        elif event.kind == "model_start":
            print(f"\n[model step {event.payload['step']}] thinking...", flush=True)
        elif event.kind == "model_delta":
            continue
        elif event.kind == "model":
            parsed = event.payload.get("parsed") or {}
            thought = parsed.get("thought") if isinstance(parsed, dict) else None
            if thought:
                print(f"[model] {thought}", flush=True)
        elif event.kind == "action":
            tool = event.payload["tool"]
            reason = event.payload.get("reason") or ""
            suffix = f" - {reason}" if reason else ""
            print(f"\n[action] {tool}{suffix}")
        elif event.kind == "error":
            print(f"\n[error] {event.payload['message']}")
        elif event.kind == "final":
            print(f"\n[final] {event.payload['message']}")


def _print_stream_delta(
    event: AgentEvent,
    *,
    role: str,
    streaming_segment: str | None,
    streaming_had_reasoning: bool,
) -> tuple[str | None, bool]:
    reasoning = event.payload.get("reasoning") or ""
    content = event.payload.get("content") or ""
    if reasoning:
        if streaming_segment != "reasoning":
            print(f"\n[{role} reasoning] ", end="", flush=True)
            streaming_segment = "reasoning"
        print(reasoning, end="", flush=True)
        streaming_had_reasoning = True
    if content:
        if streaming_had_reasoning and streaming_segment != "content":
            print(f"\n[{role} output] ", end="", flush=True)
            streaming_segment = "content"
        print(content, end="", flush=True)
    return streaming_segment, streaming_had_reasoning


if __name__ == "__main__":
    raise SystemExit(main())
