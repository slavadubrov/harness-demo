"""Execute a frozen trusted grader against captured data, then bind acceptance."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

from .artifacts import Artifact, capture, digest, json_bytes
from .suite import EvalTask


@dataclass(frozen=True)
class Evidence:
    artifact_sha256: str
    task_sha256: str
    grader_sha256: str
    split: str
    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    status: str
    python: str


def grade(
    artifact: Artifact,
    task: EvalTask,
    *,
    split: Literal["examples", "holdout"] = "holdout",
) -> Evidence:
    if split not in ("examples", "holdout"):
        raise ValueError("Unknown scoring split")
    grader = Path(__file__).with_name("grader.py").read_bytes()
    start = perf_counter()
    exit_code = None
    stdout = ""
    stderr = ""
    status = "invalid_artifact"
    command = (sys.executable, "-I", "grader.py")
    # Every file is hashed; only the allowlisted configuration is interpreted.
    config_files = [file for file in artifact.files if file.path == "config.json"]
    if len(config_files) == 1:
        try:
            config = config_files[0].content.decode("utf-8")
        except UnicodeDecodeError:
            config = ""
        payload = json_bytes({"config": config, "cases": getattr(task, split)})
        with tempfile.TemporaryDirectory(prefix="harness-grade-") as directory:
            Path(directory, "grader.py").write_bytes(grader)
            try:
                result = subprocess.run(
                    command,
                    input=payload,
                    capture_output=True,
                    cwd=directory,
                    env={"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"},
                    timeout=5,
                    check=False,
                )
                exit_code = result.returncode
                stdout = result.stdout.decode("utf-8", errors="replace")
                stderr = result.stderr.decode("utf-8", errors="replace")
                status = "failed"
                if exit_code == 0:
                    expected = len(getattr(task, split))
                    if json.loads(stdout) == {
                        "schema": True,
                        "passed": expected,
                        "total": expected,
                    }:
                        status = "passed"
            except subprocess.TimeoutExpired:
                status = "timeout"
            except (OSError, ValueError):
                status = "runner_error"
    return Evidence(
        artifact.sha256,
        task.sha256,
        digest(grader),
        split,
        command,
        exit_code,
        stdout,
        stderr,
        perf_counter() - start,
        status,
        platform.python_version(),
    )


def accepts(root: Path, task: EvalTask, evidence: Evidence) -> bool:
    """Consume runner-owned evidence only; reports are not signed authorizations.

    Never deserialize a candidate-provided verdict here. A changed file, task or
    grader invalidates the previous pass. The caller must use the captured bytes
    for any subsequent effect; this does not lock a mutable checkout.
    """
    try:
        return (
            evidence.status == "passed"
            and evidence.exit_code == 0
            and evidence.split == "holdout"
            and evidence.artifact_sha256 == capture(root).sha256
            and evidence.task_sha256 == task.sha256
            and evidence.grader_sha256
            == digest(Path(__file__).with_name("grader.py").read_bytes())
        )
    except (OSError, ValueError):
        return False
