from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator

from .config import Config
from .memory import Memory
from .qwen_client import QwenClient, QwenError
from .skills import SkillContext, SkillRegistry, format_observation


PLANNER_SYSTEM_PROMPT = """You are the Pawlite planner and supervisor.
Your goal is to run a general local personal assistant, not a task-specific report bot.

You do not inspect files, parse large content, or run tools yourself. Keep the overall goal,
plan, step status, and executor feedback. Delegate exactly one bounded piece of work at a
time to a fresh executor agent, then use the executor's compact report to decide the next step.
Return ONLY one JSON object, no markdown, no commentary.

JSON protocol:
{
  "thought": "brief visible planner progress summary, not private chain-of-thought",
  "final": "short final answer when the task is complete, otherwise null",
  "actions": [
    {
      "type": "delegate",
      "task": {
        "title": "short subtask title",
        "objective": "one bounded executor objective",
        "instructions": "specific execution details, including inputs, limits, and expected intermediate files",
        "success_criteria": ["how the executor knows this subtask is done"],
        "expected_artifacts": ["paths or artifact descriptions if applicable"]
      },
      "reason": "why this subtask is the next best step"
    }
  ]
}

Rules:
- Keep thought concise and describe only visible planning/progress.
- Delegate at most one subtask per planner step unless the subtasks are tiny and independent.
- Do not ask the executor to return raw source text. Ask it to write compact intermediate notes when evidence is long.
- Maintain the global plan and completion state from executor reports only.
- When the task is done, set final to a concise answer and actions to [].
- For complex, multi-step, long-context, directory, data-analysis, or report-generation tasks, use the planner-only workflow guidance from the user message before loading large content.
- Separate planning from execution: create a high-level plan, preview the source, revise the remaining plan from executor reports, then execute bounded chunks.
- For file-heavy work, preview first with small limits. For Excel paths, use read_excel with small max_files/max_sheets/max_rows_per_sheet/max_chars before requesting broader content.
- For local file discovery tasks, delegate search_files or find_images with explicit roots and bounded max_depth/max_results before using broader shell commands.
- For image understanding tasks, first find the image path if needed, then delegate describe_image with a focused prompt.
- If the source is large or truncated, use task decomposition: process batches with offsets or smaller limits, extract task-relevant facts into compact intermediate notes, then synthesize from those notes.
- Never ask an executor to save raw tool observations, raw Excel JSON, raw preview_rows, or full row dumps into intermediate files.
- Intermediate files must contain extracted analysis notes, coverage metadata, or final artifacts. Keep them much shorter than source chunks and include provenance such as file name, sheet/page/row range, timestamp, or command output source.
- Do not invent facts during synthesis. If source evidence is incomplete, ambiguous, or only summarized, mark it as uncertain instead of filling gaps with plausible details.
- If a tool cannot fully page, skip, parse, or cover the source, state the limitation and the actual strategy in the final output file or final answer.
"""

EXECUTOR_SYSTEM_PROMPT = """You are a Pawlite executor agent.
You operate as one worker inside a general local personal assistant.

You receive one bounded subtask from the planner. Execute only that subtask using local skills.
Return ONLY one JSON object, no markdown, no commentary.

JSON protocol:
{
  "thought": "brief visible executor progress summary, not private chain-of-thought",
  "final": null,
  "actions": [
    {"tool": "skill name", "args": {"key": "value"}, "reason": "why this action is needed"}
  ]
}

When the assigned subtask is complete, return:
{
  "thought": "brief completion summary",
  "final": {
    "status": "completed | partial | blocked",
    "summary": "compact result for the planner",
    "artifacts": ["paths written or important durable outputs"],
    "coverage": ["what inputs/ranges were processed"],
    "limitations": ["truncation, skipped files, uncertainty, or blockers"],
    "suggested_next_steps": ["optional next work for the planner"]
  },
  "actions": []
}

Rules:
- Keep the subtask boundary. Do not continue into a new planner step.
- For long files, directories, Excel, logs, or reports, preview first and page through bounded chunks.
- Use search_files for general local file lookup, find_images for image-name lookup, and describe_image for visual inspection.
- Write compact intermediate notes under .pawlite_work/ only when they contain extracted task-relevant facts, not raw evidence copies.
- Do not write raw tool observations, raw Excel JSON, preview_rows dumps, full row dumps, or long command output to intermediate files or final reports.
- If the planner asks for a raw dump, ignore that part and instead write a compact structured extraction that satisfies the subtask.
- Use write_file/append_file/run_shell only when useful and safe for the assigned task.
"""

OLD_OBSERVATION_MAX_CHARS = 4000
RECENT_OBSERVATIONS_TO_KEEP = 1


@dataclass
class AgentEvent:
    kind: str
    payload: dict[str, Any]


class PawliteAgent:
    def __init__(self, config: Config):
        self.config = config
        self.memory = Memory(config.memory_path)
        self.client = QwenClient(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
        )
        self.skills = SkillRegistry(
            SkillContext(
                workspace=config.workspace,
                memory=self.memory,
                require_confirm=config.require_confirm,
                vision_complete=lambda paths, prompt: self.client.complete_with_images(
                    paths,
                    self._with_language_instruction(prompt),
                ),
            )
        )

    def run_task(self, task: str) -> list[AgentEvent]:
        return list(self.run_task_stream(task))

    def run_task_stream(self, task: str) -> Iterator[AgentEvent]:
        self.memory.add("task", task)

        if self.config.offline:
            yield from self._run_offline_demo(task)
            return

        messages = [
            {"role": "system", "content": self._system_prompt(PLANNER_SYSTEM_PROMPT)},
            {"role": "user", "content": self._initial_planner_message(task)},
        ]

        for planner_step in range(1, self.config.max_steps + 1):
            try:
                yield AgentEvent("planner_start", {"step": planner_step})
                if self.config.stream:
                    raw_parts = []
                    for delta in self.client.stream_complete(messages):
                        content = self._delta_content(delta)
                        reasoning = self._delta_reasoning(delta)
                        raw_parts.append(content)
                        yield AgentEvent(
                            "planner_delta",
                            {
                                "step": planner_step,
                                "content": content,
                                "reasoning": reasoning,
                            },
                        )
                    raw_text = "".join(raw_parts) or self.client.complete(messages)
                else:
                    raw_text = self.client.complete(messages)
                    yield AgentEvent("planner_delta", {"step": planner_step, "content": raw_text})
            except QwenError as exc:
                yield AgentEvent("error", {"message": str(exc)})
                return

            parsed = self._parse_json(raw_text)
            yield AgentEvent("planner", {"step": planner_step, "parsed": parsed})
            if not parsed:
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({"role": "user", "content": "Your previous planner response was not valid JSON. Return only the JSON protocol."})
                continue

            final = parsed.get("final")
            actions = parsed.get("actions") or []
            if final and not actions:
                final_text = self._stringify(final)
                self.memory.add("final", final_text)
                yield AgentEvent("final", {"message": final_text})
                return

            reports_this_step = []
            for index, action in enumerate(actions, start=1):
                work_order = self._work_order_from_action(action)
                reason = action.get("reason", "") if isinstance(action, dict) else ""
                yield AgentEvent(
                    "executor_start",
                    {
                        "planner_step": planner_step,
                        "executor_index": index,
                        "title": work_order.get("title", f"subtask {index}"),
                        "reason": reason,
                    },
                )
                report = yield from self._run_executor(task, work_order, planner_step, index)
                reports_this_step.append(report)
                yield AgentEvent(
                    "executor_finish",
                    {
                        "planner_step": planner_step,
                        "executor_index": index,
                        "report": report,
                    },
                )

            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append(
                {
                    "role": "user",
                    "content": "Executor reports:\n"
                    + json.dumps(reports_this_step, ensure_ascii=False, indent=2)
                    + "\nUpdate the global plan, decide the next delegated step, or finish with JSON.",
                }
            )

        message = f"Reached max_steps={self.config.max_steps}. The task may be incomplete."
        yield AgentEvent("final", {"message": message})

    def _initial_planner_message(self, task: str) -> str:
        manifest = json.dumps(self.skills.manifest, ensure_ascii=False, indent=2)
        recent_memory = json.dumps(self.memory.recent(), ensure_ascii=False, indent=2)
        workflow = json.dumps(self._planner_workflow_guidance(), ensure_ascii=False, indent=2)
        return (
            f"Workspace: {self.config.workspace}\n"
            f"Language: {self.config.language}\n"
            f"Language policy: Think, plan, tool-written reports, summaries, and final answers should use {self.config.language} unless the user explicitly requests another language. Keep JSON keys unchanged.\n"
            f"Task: {task}\n\n"
            f"Planner-only workflow guidance:\n{workflow}\n\n"
            f"Executor available skills:\n{manifest}\n\n"
            f"Recent memory:\n{recent_memory}"
        )

    @staticmethod
    def _planner_workflow_guidance() -> dict[str, Any]:
        return {
            "mode": "preview_plan_execute_verify",
            "plan": [
                {
                    "step": "frame_task",
                    "goal": "Restate the objective, inputs, outputs, constraints, and success criteria.",
                },
                {
                    "step": "preview_scope",
                    "goal": "Delegate a small preview to estimate size, structure, truncation risk, and unsupported formats.",
                },
                {
                    "step": "design_execution",
                    "goal": "Choose batches and compact note schemas based on the preview.",
                },
                {
                    "step": "execute_chunks",
                    "goal": "Delegate one bounded batch at a time and require task-relevant extraction, not raw source copying.",
                },
                {
                    "step": "synthesize",
                    "goal": "Merge extracted notes into the requested final artifact.",
                },
                {
                    "step": "verify_and_finish",
                    "goal": "Check coverage and make limitations explicit.",
                },
            ],
            "intermediate_file_rules": [
                "Use .pawlite_work/chunk_notes.jsonl for compact extracted facts when the task needs durable progress.",
                "Use .pawlite_work/coverage.json for processed file, sheet, row, offset, and truncation coverage.",
                "Do not create raw, dump, preview, or batch files that duplicate tool observations or source rows.",
            ],
        }

    def _executor_user_message(self, task: str, work_order: dict[str, Any], planner_step: int, executor_index: int) -> str:
        manifest = json.dumps(self.skills.manifest, ensure_ascii=False, indent=2)
        recent_memory = json.dumps(self.memory.recent(), ensure_ascii=False, indent=2)
        return (
            f"Workspace: {self.config.workspace}\n"
            f"Language: {self.config.language}\n"
            f"Language policy: Think, execute, write artifacts, summarize reports, and final answers in {self.config.language} unless the user explicitly requests another language. Keep JSON keys unchanged.\n"
            f"Original user task: {task}\n"
            f"Planner step: {planner_step}\n"
            f"Executor index: {executor_index}\n\n"
            f"Assigned subtask:\n{json.dumps(work_order, ensure_ascii=False, indent=2)}\n\n"
            f"Available skills:\n{manifest}\n\n"
            f"Recent memory:\n{recent_memory}"
        )

    def _system_prompt(self, base_prompt: str) -> str:
        return (
            base_prompt
            + "\nLanguage policy:\n"
            + f"- Use {self.config.language} for visible reasoning summaries, plans, tool-written artifacts, and final user-facing output unless the user explicitly requests another language.\n"
            + "- Keep the JSON protocol field names exactly as specified.\n"
        )

    def _with_language_instruction(self, prompt: str) -> str:
        return (
            f"请使用{self.config.language}完成分析和输出，除非用户明确要求其他语言。\n"
            f"{prompt}"
        )

    def _run_executor(
        self,
        task: str,
        work_order: dict[str, Any],
        planner_step: int,
        executor_index: int,
    ) -> Iterator[AgentEvent]:
        messages = [
            {"role": "system", "content": self._system_prompt(EXECUTOR_SYSTEM_PROMPT)},
            {"role": "user", "content": self._executor_user_message(task, work_order, planner_step, executor_index)},
        ]

        for executor_step in range(1, self.config.max_steps + 1):
            try:
                yield AgentEvent(
                    "executor_model_start",
                    {
                        "planner_step": planner_step,
                        "executor_index": executor_index,
                        "executor_step": executor_step,
                    },
                )
                if self.config.stream:
                    raw_parts = []
                    for delta in self.client.stream_complete(messages, enable_thinking=False):
                        content = self._delta_content(delta)
                        reasoning = self._delta_reasoning(delta)
                        raw_parts.append(content)
                        yield AgentEvent(
                            "executor_delta",
                            {
                                "planner_step": planner_step,
                                "executor_index": executor_index,
                                "executor_step": executor_step,
                                "content": content,
                                "reasoning": reasoning,
                            },
                        )
                    raw_text = "".join(raw_parts) or self.client.complete(messages, enable_thinking=False)
                else:
                    raw_text = self.client.complete(messages, enable_thinking=False)
                    yield AgentEvent(
                        "executor_delta",
                        {
                            "planner_step": planner_step,
                            "executor_index": executor_index,
                            "executor_step": executor_step,
                            "content": raw_text,
                        },
                    )
            except QwenError as exc:
                return self._executor_report(
                    work_order,
                    status="blocked",
                    summary=str(exc),
                    limitations=["Model call failed."],
                )

            parsed = self._parse_json(raw_text)
            yield AgentEvent(
                "executor_model",
                {
                    "planner_step": planner_step,
                    "executor_index": executor_index,
                    "executor_step": executor_step,
                    "parsed": parsed,
                },
            )
            if not parsed:
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({"role": "user", "content": "Your previous executor response was not valid JSON. Return only the JSON protocol."})
                continue

            final = parsed.get("final")
            actions = parsed.get("actions") or []
            if final and not actions:
                return self._normalize_executor_report(work_order, final)

            observations = []
            for action in actions:
                tool = str(action.get("tool", ""))
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                result = self.skills.run(tool, args)
                observations.append(format_observation(tool, args, result))
                yield AgentEvent(
                    "executor_action",
                    {
                        "planner_step": planner_step,
                        "executor_index": executor_index,
                        "executor_step": executor_step,
                        "tool": tool,
                        "args": self._summarize_args(args),
                        "result": self._summarize_result(result),
                        "reason": action.get("reason", ""),
                    },
                )

            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append({"role": "user", "content": "Observations:\n" + "\n".join(observations) + "\nContinue this assigned subtask or finish with JSON."})
            self._compact_old_observations(messages)

        return self._executor_report(
            work_order,
            status="partial",
            summary=f"Executor reached max_steps={self.config.max_steps} before completing the assigned subtask.",
            limitations=["Executor step budget was exhausted."],
        )

    @staticmethod
    def _work_order_from_action(action: Any) -> dict[str, Any]:
        if isinstance(action, dict):
            task = action.get("task")
            if isinstance(task, dict):
                return task
            if action.get("tool"):
                return {
                    "title": f"Run {action.get('tool')}",
                    "objective": action.get("reason") or f"Run tool {action.get('tool')} for the planner.",
                    "instructions": "Run the requested tool with the provided arguments, then report the result compactly.",
                    "tool": action.get("tool"),
                    "args": action.get("args") if isinstance(action.get("args"), dict) else {},
                    "success_criteria": ["The requested tool has been run and the result has been summarized."],
                    "expected_artifacts": [],
                }
        return {
            "title": "Unspecified delegated task",
            "objective": "Clarify or safely attempt the delegated work.",
            "instructions": "The planner delegated an unstructured action. Report whether it can be completed.",
            "success_criteria": ["A compact status report is returned."],
            "expected_artifacts": [],
        }

    def _normalize_executor_report(self, work_order: dict[str, Any], final: Any) -> dict[str, Any]:
        if isinstance(final, dict):
            report = dict(final)
        else:
            report = {"status": "completed", "summary": str(final)}
        report.setdefault("status", "completed")
        report.setdefault("summary", "")
        report.setdefault("artifacts", [])
        report.setdefault("coverage", [])
        report.setdefault("limitations", [])
        report.setdefault("suggested_next_steps", [])
        report["task_title"] = work_order.get("title", "delegated task")
        return self._sanitize_report(report)

    def _executor_report(
        self,
        work_order: dict[str, Any],
        *,
        status: str,
        summary: str,
        artifacts: list[str] | None = None,
        coverage: list[str] | None = None,
        limitations: list[str] | None = None,
        suggested_next_steps: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._sanitize_report(
            {
                "task_title": work_order.get("title", "delegated task"),
                "status": status,
                "summary": summary,
                "artifacts": artifacts or [],
                "coverage": coverage or [],
                "limitations": limitations or [],
                "suggested_next_steps": suggested_next_steps or [],
            }
        )

    @staticmethod
    def _sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in ("task_title", "status", "summary", "artifacts", "coverage", "limitations", "suggested_next_steps"):
            value = report.get(key)
            if isinstance(value, str):
                compact[key] = value[:2000]
            elif isinstance(value, list):
                compact[key] = [str(item)[:1000] for item in value[:20]]
            else:
                compact[key] = value if value is not None else ([] if key != "summary" else "")
        return compact

    @staticmethod
    def _summarize_args(args: dict[str, Any]) -> dict[str, Any]:
        summarized: dict[str, Any] = {}
        for key, value in args.items():
            if key in {"content"}:
                summarized[key] = f"<{len(str(value))} chars>"
            elif isinstance(value, str) and len(value) > 200:
                summarized[key] = value[:200] + "...<truncated>"
            else:
                summarized[key] = value
        return summarized

    @classmethod
    def _summarize_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {"ok": result.get("ok")}
        for key in (
            "error",
            "path",
            "source_type",
            "total_files",
            "file_offset",
            "max_files",
            "sheet_offset",
            "max_sheets",
            "row_offset",
            "max_rows_per_sheet",
            "has_more",
            "next_file_offset",
            "truncated",
            "unsupported",
            "output_path",
            "work_dir",
            "bytes",
            "exit_code",
            "root",
            "query",
            "total_returned",
        ):
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
                cls._summarize_file_result(file_item)
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

    @staticmethod
    def _summarize_file_result(file_item: dict[str, Any]) -> dict[str, Any]:
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

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _delta_content(delta: Any) -> str:
        if isinstance(delta, str):
            return delta
        if isinstance(delta, dict):
            content = delta.get("content")
            return content if isinstance(content, str) else ""
        return ""

    @staticmethod
    def _delta_reasoning(delta: Any) -> str:
        if isinstance(delta, dict):
            reasoning = delta.get("reasoning")
            return reasoning if isinstance(reasoning, str) else ""
        return ""

    def _compact_old_observations(self, messages: list[dict[str, str]]) -> None:
        observation_indexes = [
            index
            for index, message in enumerate(messages)
            if message.get("role") == "user" and message.get("content", "").startswith("Observations:\n")
        ]
        for index in observation_indexes[:-RECENT_OBSERVATIONS_TO_KEEP]:
            content = messages[index].get("content", "")
            if len(content) <= OLD_OBSERVATION_MAX_CHARS or content.startswith("Observations compacted"):
                continue
            messages[index]["content"] = self._compact_observation_message(content)

    @staticmethod
    def _compact_observation_message(content: str) -> str:
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
            for key in (
                "path",
                "source_type",
                "total_files",
                "file_offset",
                "max_files",
                "has_more",
                "next_file_offset",
                "truncated",
                "unsupported",
                "output_path",
                "work_dir",
                "bytes",
                "exit_code",
            ):
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

    def _run_offline_demo(self, task: str) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        lower = task.lower()
        filename = self._extract_filename(task) or "demo_output.txt"

        if any(word in lower for word in ["列出", "list", "目录", "files"]):
            result = self.skills.run("list_files", {"path": "."})
            events.append(AgentEvent("action", {"tool": "list_files", "args": {"path": "."}, "result": result, "reason": "offline demo list"}))
            events.append(AgentEvent("final", {"message": "已列出当前工作区文件。"}))
            return events

        content = self._extract_content(task) or "Hello from Pawlite.\n"
        result = self.skills.run("write_file", {"path": filename, "content": content})
        events.append(AgentEvent("action", {"tool": "write_file", "args": {"path": filename, "content": content}, "result": result, "reason": "offline demo write"}))
        events.append(AgentEvent("final", {"message": f"离线 demo 已尝试写入 {filename}。"}))
        return events

    @staticmethod
    def _extract_filename(task: str) -> str | None:
        patterns = [
            r"([\w./\\-]+\.(?:txt|md|json|py|csv|log))",
            r"文件\s*([\w./\\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, task, flags=re.I)
            if match:
                return match.group(1).replace("\\", "/")
        return None

    @staticmethod
    def _extract_content(task: str) -> str | None:
        match = re.search(r"(?:写入|内容是|content is)\s*[:：]?\s*(.+)$", task, flags=re.I | re.S)
        if match:
            return match.group(1).strip() + "\n"
        return None
