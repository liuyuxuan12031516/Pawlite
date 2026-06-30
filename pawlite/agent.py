from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterator

from .agent_reports import executor_report, normalize_executor_report
from .config import Config
from .memory import Memory
from .observations import compact_old_observations, summarize_args, summarize_result
from .offline import run_offline_demo
from .planner_skills import PlannerSkillStore
from .prompts import EXECUTOR_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT, call_guardrail, system_prompt, with_language_instruction
from .qwen_client import QwenClient, QwenError
from .skills import SkillContext, SkillRegistry, format_observation


PLANNER_THINKING_BUDGET = 500


@dataclass
class AgentEvent:
    kind: str
    payload: dict[str, Any]


class PawliteAgent:
    def __init__(self, config: Config):
        self.config = config
        self.memory = Memory(config.memory_path)
        self.client = QwenClient.from_config(config)
        self.planner_skills = PlannerSkillStore(config.workspace)
        self.skills = SkillRegistry(
            SkillContext(
                workspace=config.workspace,
                memory=self.memory,
                require_confirm=config.require_confirm,
                vision_complete=lambda paths, prompt: self.client.complete_with_images(
                    paths,
                    self._with_language_instruction(prompt),
                ),
                web_search_complete=lambda query, search_strategy: self.client.web_search(
                    self._with_language_instruction(query),
                    search_strategy=search_strategy,
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
                raw_text = yield from self._model_turn(
                    messages,
                    actor="planner",
                    start_kind="planner_start",
                    delta_kind="planner_delta",
                    start_payload={"step": planner_step},
                    delta_payload={"step": planner_step},
                    enable_thinking=True,
                    thinking_budget=PLANNER_THINKING_BUDGET,
                )
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
                if self._is_read_skill_action(action):
                    reason = action.get("reason", "") if isinstance(action, dict) else ""
                    name = str(action.get("name") or action.get("skill") or "").strip()
                    title = f"Read skill: {name or 'unknown'}"
                    yield self._executor_start_event(planner_step, index, title, reason)
                    report = self._read_planner_skill_report(name)
                    reports_this_step.append(report)
                    yield self._executor_finish_event(planner_step, index, report)
                    continue

                work_order = self._work_order_from_action(action)
                reason = action.get("reason", "") if isinstance(action, dict) else ""
                yield self._executor_start_event(
                    planner_step,
                    index,
                    str(work_order.get("title", f"subtask {index}")),
                    reason,
                )
                report = yield from self._run_executor(task, work_order, planner_step, index)
                reports_this_step.append(report)
                yield self._executor_finish_event(planner_step, index, report)

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
        planner_skills = json.dumps(self._planner_skill_catalog(), ensure_ascii=False, indent=2)
        return (
            f"Workspace: {self.config.workspace}\n"
            f"Language: {self.config.language}\n"
            f"Language policy: Think, plan, tool-written reports, summaries, and final answers should use {self.config.language} unless the user explicitly requests another language. Keep JSON keys unchanged.\n"
            f"Task: {task}\n\n"
            f"Planner-only workflow guidance:\n{workflow}\n\n"
            f"External planner skill catalog (summaries only; request read_skill by name only when relevant):\n{planner_skills}\n\n"
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
                    "goal": "Delegate one bounded batch at a time, sized to the executor step budget, and require task-relevant extraction, not raw source copying.",
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

    def _planner_skill_catalog(self) -> list[dict[str, str]]:
        return self.planner_skills.catalog()

    @staticmethod
    def _is_read_skill_action(action: Any) -> bool:
        return isinstance(action, dict) and action.get("type") == "read_skill"

    @staticmethod
    def _executor_start_event(planner_step: int, executor_index: int, title: str, reason: str) -> AgentEvent:
        return AgentEvent(
            "executor_start",
            {
                "planner_step": planner_step,
                "executor_index": executor_index,
                "title": title,
                "reason": reason,
            },
        )

    @staticmethod
    def _executor_finish_event(planner_step: int, executor_index: int, report: dict[str, Any]) -> AgentEvent:
        return AgentEvent(
            "executor_finish",
            {
                "planner_step": planner_step,
                "executor_index": executor_index,
                "report": report,
            },
        )

    def _read_planner_skill_report(self, name: str) -> dict[str, Any]:
        return self.planner_skills.read_report(name)

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
        return system_prompt(base_prompt, self.config.language)

    def _messages_for_call(self, messages: list[dict[str, str]], *, actor: str) -> list[dict[str, str]]:
        return [
            *messages,
            {
                "role": "user",
                "content": self._call_guardrail(actor),
            },
        ]

    def _call_guardrail(self, actor: str) -> str:
        return call_guardrail(actor, self.config.language)

    def _with_language_instruction(self, prompt: str) -> str:
        return with_language_instruction(prompt, self.config.language)

    def _stream_or_complete(
        self,
        messages: list[dict[str, str]],
        *,
        event_kind: str,
        event_payload: dict[str, Any],
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> Iterator[AgentEvent | str]:
        raw_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            for delta in self.client.stream_complete(
                messages,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            ):
                content = self._delta_content(delta)
                reasoning = self._delta_reasoning(delta)
                raw_parts.append(content)
                reasoning_parts.append(reasoning)
                yield AgentEvent(
                    event_kind,
                    {
                        **event_payload,
                        "content": content,
                        "reasoning": reasoning,
                    },
                )
            raw_text = "".join(raw_parts)
            if raw_text:
                return {"content": raw_text, "reasoning": "".join(reasoning_parts)}
        except QwenError:
            pass
        raw_text = self.client.complete(
            messages,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )
        yield AgentEvent(event_kind, {**event_payload, "content": raw_text, "reasoning": ""})
        return {"content": raw_text, "reasoning": ""}

    def _model_turn(
        self,
        messages: list[dict[str, str]],
        *,
        actor: str,
        start_kind: str,
        delta_kind: str,
        start_payload: dict[str, Any],
        delta_payload: dict[str, Any],
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> Iterator[AgentEvent | str]:
        yield AgentEvent(start_kind, start_payload)
        call_messages = self._messages_for_call(messages, actor=actor)
        yield AgentEvent(
            "model_input",
            {
                **start_payload,
                "actor": actor,
                "enable_thinking": enable_thinking,
                "thinking_budget": thinking_budget,
                "messages": call_messages,
            },
        )
        if self.config.stream:
            output = yield from self._stream_or_complete(
                call_messages,
                event_kind=delta_kind,
                event_payload=delta_payload,
                enable_thinking=enable_thinking,
                thinking_budget=thinking_budget,
            )
            raw_text = output["content"]
            yield AgentEvent(
                "model_output",
                {
                    **delta_payload,
                    "actor": actor,
                    "content": raw_text,
                    "reasoning": output.get("reasoning", ""),
                },
            )
            return raw_text

        raw_text = self.client.complete(
            call_messages,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        )
        yield AgentEvent(delta_kind, {**delta_payload, "content": raw_text, "reasoning": ""})
        yield AgentEvent(
            "model_output",
            {
                **delta_payload,
                "actor": actor,
                "content": raw_text,
                "reasoning": "",
            },
        )
        return raw_text

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
                event_payload = {
                    "planner_step": planner_step,
                    "executor_index": executor_index,
                    "executor_step": executor_step,
                }
                raw_text = yield from self._model_turn(
                    messages,
                    actor="executor",
                    start_kind="executor_model_start",
                    delta_kind="executor_delta",
                    start_payload=event_payload,
                    delta_payload=event_payload,
                    enable_thinking=False,
                )
            except QwenError as exc:
                return executor_report(
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
                return normalize_executor_report(work_order, final)

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
                        "args": summarize_args(args),
                        "result": summarize_result(result),
                        "reason": action.get("reason", ""),
                    },
                )

            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            messages.append({"role": "user", "content": "Observations:\n" + "\n".join(observations) + "\nContinue this assigned subtask or finish with JSON."})
            compact_old_observations(messages)

        return executor_report(
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

    def _run_offline_demo(self, task: str) -> list[AgentEvent]:
        return run_offline_demo(task, self.skills, AgentEvent)
