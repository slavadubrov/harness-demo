"""Explicit offline execution and opt-in live evaluation; simulation stays default."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .artifacts import capture, write_json
from .runner import accepts, grade
from .suite import SUITE


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser(
        "fixture", help="grade submitted data without a model"
    )
    fixture.add_argument("directory", type=Path)
    fixture.add_argument(
        "--task", choices=[task.name for task in SUITE], default="slug"
    )
    fixture.add_argument("--output", type=Path)
    live = commands.add_parser("live", help="make bounded, billable OpenAI calls")
    live.add_argument(
        "--model", required=True, help="explicit model or pinned snapshot ID"
    )
    live.add_argument(
        "--task", choices=[task.name for task in SUITE] + ["all"], default="slug"
    )
    live.add_argument("--trials", type=int, default=1)
    live.add_argument("--max-output-tokens", type=int, default=1024)
    live.add_argument(
        "--reasoning-effort", choices=["low", "medium", "high"], default="low"
    )
    live.add_argument("--drop-reasoning", action="store_true")
    live.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fixture":
            task = next(task for task in SUITE if task.name == args.task)
            if args.output and args.output.resolve().is_relative_to(
                args.directory.resolve()
            ):
                raise ValueError("Write evidence outside the submitted directory")
            artifact = capture(args.directory)
            evidence = grade(artifact, task)
            accepted = accepts(args.directory, task, evidence)
            fixture_report = {
                "schema_version": 1,
                "lane": "fixture",
                "accepted": accepted,
                "artifact": artifact.manifest(),
                "evidence": asdict(evidence),
            }
            if args.output:
                write_json(args.output, fixture_report)
            print(json.dumps(fixture_report, indent=2))
            return 0 if accepted else 1
        from .experiment import Settings, run_experiment
        from .provider import OpenAIProvider

        settings = Settings(
            args.model,
            args.trials,
            args.max_output_tokens,
            args.reasoning_effort,
            not args.drop_reasoning,
        )
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "Set OPENAI_API_KEY; use uv run --env-file .env --extra live ..."
            )
        if args.output.exists():
            raise ValueError(
                "Choose a new output path; existing live evidence is preserved"
            )
        tasks = tuple(task for task in SUITE if args.task in (task.name, "all"))
        provider = OpenAIProvider(key)
        try:
            report = run_experiment(tasks, settings, provider.generate, args.output)
        finally:
            provider.close()
        print(
            json.dumps(
                {"status": report["status"], "summary": report["summary"]}, indent=2
            )
        )
        return 0 if all(row["status"] == "passed" for row in report["trials"]) else 1
    except (OSError, ValueError, ImportError) as exc:
        print(f"harness-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
