"""Paired feedback experiment with fixed two-call arms and failure accounting."""

from __future__ import annotations

import platform
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

from .artifacts import candidate, digest, json_bytes, write_json
from .provider import ProviderFailure, Reply, response_format
from .runner import grade
from .suite import EvalTask


@dataclass(frozen=True)
class Settings:
    model: str
    trials: int = 1
    max_output_tokens: int = 1024
    reasoning_effort: str = "low"
    retain_reasoning: bool = True

    def __post_init__(self) -> None:
        if not self.model.strip() or not 1 <= self.trials <= 10:
            raise ValueError("Provide a model and 1–10 trials")
        if not 128 <= self.max_output_tokens <= 4096:
            raise ValueError("Output budget must be 128–4096 tokens per call")
        if self.reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("Reasoning effort must be low, medium or high")


def summarize_trials(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for arm in ("blind-retry", "check-feedback"):
        subset = [row for row in rows if row["arm"] == arm]
        counts = Counter(row["status"] for row in subset)
        summary[arm] = {
            "planned": len(subset),
            "passed": counts["passed"],
            "pass_rate": counts["passed"] / len(subset) if subset else 0.0,
            "statuses": dict(counts),
        }
    pairs: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        pairs.setdefault((row["task"], row["trial"]), {})[row["arm"]] = row["status"]
    scored = [
        pair
        for pair in pairs.values()
        if set(pair) == {"blind-retry", "check-feedback"}
        and all(
            status in {"passed", "failed", "invalid_artifact"}
            for status in pair.values()
        )
    ]
    summary["paired"] = {
        "scored_pairs": len(scored),
        "excluded_pairs": len(pairs) - len(scored),
        "treatment_wins": sum(
            p["check-feedback"] == "passed" and p["blind-retry"] != "passed"
            for p in scored
        ),
        "control_wins": sum(
            p["blind-retry"] == "passed" and p["check-feedback"] != "passed"
            for p in scored
        ),
        "ties": sum(
            (p["blind-retry"] == "passed") == (p["check-feedback"] == "passed")
            for p in scored
        ),
        "note": "Descriptive scored pairs only; no population-level claim.",
    }
    return summary


def run_experiment(
    tasks: tuple[EvalTask, ...],
    settings: Settings,
    generate: Callable[[dict[str, Any]], Reply],
    output: Path,
) -> dict[str, Any]:
    if not tasks or len({task.name for task in tasks}) != len(tasks):
        raise ValueError("Experiment tasks must be nonempty and uniquely named")
    rows: list[dict[str, Any]] = []
    for task in tasks:
        for trial in range(settings.trials):
            arms = ("blind-retry", "check-feedback")
            for arm in arms if trial % 2 == 0 else arms[::-1]:
                rows.append(
                    {
                        "task": task.name,
                        "trial": trial,
                        "arm": arm,
                        "status": "not_run",
                        "attempts": [],
                    }
                )
    try:
        sdk_version = version("openai")
    except PackageNotFoundError:
        sdk_version = "not-installed"
    implementation = {
        path.name: digest(path.read_bytes())
        for path in sorted(Path(__file__).parent.glob("*.py"))
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "lane": "live",
        "status": "running",
        "settings": asdict(settings),
        "api": "responses",
        "store": False,
        "compaction": "disabled",
        "sdk_retries": 0,
        "timeout_seconds": 30,
        "max_calls": len(rows) * 2,
        "max_generated_tokens": len(rows) * 2 * settings.max_output_tokens,
        "python": platform.python_version(),
        "openai_sdk": sdk_version,
        "implementation": implementation,
        "suite_sha256": digest(json_bytes([asdict(task) for task in tasks])),
        "tasks": [asdict(task) for task in tasks],
        "trials": rows,
        "usage_known": True,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    task_by_name = {task.name: task for task in tasks}
    write_json(output, report)
    stopped = False
    for row in rows:
        if stopped:
            row["status"] = "not_run_after_provider_failure"
            continue
        task = task_by_name[row["task"]]
        history: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": task.instruction
                + "\nPublic examples: "
                + str(task.examples),
            }
        ]
        for attempt in range(2):
            request = {
                "model": settings.model,
                "input": list(history),
                "instructions": "Return only a normalizer config matching the request.",
                "reasoning": {"effort": settings.reasoning_effort},
                "max_output_tokens": settings.max_output_tokens,
                "store": False,
                "text": response_format(),
            }
            if settings.retain_reasoning:
                request["include"] = ["reasoning.encrypted_content"]
            entry: dict[str, Any] = {
                "attempt": attempt + 1,
                "request_sha256": digest(json_bytes(request)),
            }
            row["attempts"].append(entry)
            start = perf_counter()
            try:
                reply = generate(request)
            except ProviderFailure as exc:
                entry.update(
                    {
                        "status": "provider_failure",
                        "code": exc.code,
                        "parameter": exc.parameter,
                        "request_id": exc.request_id,
                        "response_id": exc.response_id,
                        "partial_output_discarded": exc.partial_output,
                    }
                )
                entry["latency_seconds"] = perf_counter() - start
                row["status"] = "provider_failure"
                report["usage_known"] = False
                stopped = True
                write_json(output, report)
                break
            entry.update(
                {
                    "model": reply.model,
                    "response_id": reply.response_id,
                    "request_id": reply.request_id,
                    "input_tokens": reply.input_tokens,
                    "output_tokens": reply.output_tokens,
                    "latency_seconds": perf_counter() - start,
                }
            )
            report["input_tokens"] += reply.input_tokens
            report["output_tokens"] += reply.output_tokens
            try:
                artifact = candidate(reply.text)
            except ValueError:
                entry["status"] = "invalid_artifact"
                row["status"] = "failed"
                feedback = "Configuration exceeds the artifact size limit."
            else:
                evidence = grade(
                    artifact, task, split="examples" if attempt == 0 else "holdout"
                )
                entry.update(
                    {
                        "status": evidence.status,
                        "evidence": asdict(evidence),
                        "artifact": artifact.manifest(),
                    }
                )
                row["status"] = evidence.status
                feedback = evidence.stdout or evidence.status
            if attempt == 0:
                row["status"] = "awaiting_final"
            history.extend(
                item
                for item in reply.output
                if settings.retain_reasoning or item["type"] != "reasoning"
            )
            history.append(
                {
                    "role": "user",
                    "content": (
                        "Public check result: " + feedback
                        if row["arm"] == "check-feedback"
                        else "Review your configuration again."
                    )
                    + " Return the final configuration.",
                }
            )
            write_json(output, report)
    report["status"] = "stopped" if stopped else "completed"
    report["summary"] = summarize_trials(rows)
    write_json(output, report)
    return report
