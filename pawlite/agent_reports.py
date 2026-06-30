from __future__ import annotations

from typing import Any


REPORT_KEYS = ("task_title", "status", "summary", "artifacts", "coverage", "limitations", "suggested_next_steps")


def normalize_executor_report(work_order: dict[str, Any], final: Any) -> dict[str, Any]:
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
    return sanitize_report(report)


def executor_report(
    work_order: dict[str, Any],
    *,
    status: str,
    summary: str,
    artifacts: list[str] | None = None,
    coverage: list[str] | None = None,
    limitations: list[str] | None = None,
    suggested_next_steps: list[str] | None = None,
) -> dict[str, Any]:
    return sanitize_report(
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


def sanitize_report(report: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in REPORT_KEYS:
        value = report.get(key)
        if isinstance(value, str):
            compact[key] = value[:2000]
        elif isinstance(value, list):
            compact[key] = [str(item)[:1000] for item in value[:20]]
        else:
            compact[key] = value if value is not None else ([] if key != "summary" else "")
    return compact
