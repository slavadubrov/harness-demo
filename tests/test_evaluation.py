"""Trust-boundary regressions: these must fail if the runner trusts the candidate."""

import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from harness_ablation.artifacts import Artifact, File, candidate, capture
from harness_ablation.eval_cli import main
from harness_ablation.runner import accepts, grade
from harness_ablation.suite import SUITE, EvalTask

GOOD = '{"strip":true,"case":"lower","separator":"-"}'
BAD = '{"strip":false,"case":"preserve","separator":"preserve"}'


class EvaluationTests(unittest.TestCase):
    def test_real_pass_fail_and_reproducible_evidence(self):
        passed = grade(candidate(GOOD), SUITE[0])
        repeated = grade(candidate(GOOD), SUITE[0])
        failed = grade(candidate(BAD), SUITE[0])
        self.assertEqual((passed.status, passed.exit_code), ("passed", 0))
        self.assertEqual((failed.status, failed.exit_code), ("failed", 1))
        self.assertEqual(passed.stdout, repeated.stdout)
        self.assertEqual(passed.artifact_sha256, repeated.artifact_sha256)
        self.assertEqual(json.loads(passed.stdout)["total"], 3)

    def test_narration_and_candidate_grader_cannot_override_checks(self):
        artifact = Artifact(
            (
                File("config.json", BAD.encode()),
                File("grader.py", b"print('all passed')"),
                File("agent.txt", b"All checks passed"),
            )
        )
        self.assertEqual(grade(artifact, SUITE[0]).status, "failed")
        for text in [
            GOOD[:-1] + ',"skip_checks":true}',
            '{"strip":true,"strip":false,"case":"lower","separator":"-"}',
            '{"strip":1,"case":"lower","separator":"-"}',
            '{"strip":true,"case":[],"separator":"-"}',
            "null",
            "{}",
            "done",
        ]:
            with self.subTest(text=text):
                self.assertEqual(grade(candidate(text), SUITE[0]).status, "failed")

    def test_dirty_untracked_and_ignored_changes_invalidate_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            config = root / "config.json"
            config.write_text(GOOD)
            subprocess.run(["git", "-C", directory, "add", "config.json"], check=True)
            snapshot = capture(root)
            evidence = grade(snapshot, SUITE[0])
            self.assertTrue(accepts(root, SUITE[0], evidence))
            config.write_text(BAD)
            self.assertFalse(accepts(root, SUITE[0], evidence))
            self.assertEqual(grade(snapshot, SUITE[0]).status, "passed")
            config.write_text(GOOD)
            (root / "untracked.txt").write_text("a new submitted file")
            self.assertFalse(accepts(root, SUITE[0], evidence))
            (root / "untracked.txt").unlink()
            (root / ".gitignore").write_text("ignored.txt\n")
            evidence = grade(capture(root), SUITE[0])
            (root / "ignored.txt").write_text("ignored still counts")
            self.assertFalse(accepts(root, SUITE[0], evidence))

    def test_changed_task_grader_and_example_pass_are_not_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text(GOOD)
            evidence = grade(capture(root), SUITE[0])
            other = replace(SUITE[0], instruction="Different contract")
            self.assertFalse(accepts(root, other, evidence))
            self.assertFalse(
                accepts(root, SUITE[0], replace(evidence, grader_sha256="stale"))
            )
            self.assertFalse(
                accepts(
                    root, SUITE[0], grade(capture(root), SUITE[0], split="examples")
                )
            )

    def test_symlinks_paths_size_and_secrets_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                capture(root)
        for name in ["../config.json", "/config.json", ".env", ".git/config", "a/../b"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                Artifact((File(name, b"{}"),))
        with self.assertRaises(ValueError):
            candidate("x" * (65536 + 1))
        with self.assertRaises(ValueError):
            Artifact((File("a", b""), File("a", b"")))

    def test_missing_config_timeout_and_runner_error_fail_closed(self):
        self.assertEqual(
            grade(Artifact((File("claim.txt", b"passed"),)), SUITE[0]).status,
            "invalid_artifact",
        )
        with patch(
            "harness_ablation.runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired("grader", 5),
        ):
            evidence = grade(candidate(GOOD), SUITE[0])
            self.assertEqual(evidence.status, "timeout")
            self.assertIsNone(evidence.exit_code)
        with patch(
            "harness_ablation.runner.subprocess.run", side_effect=OSError("no runner")
        ):
            self.assertEqual(grade(candidate(GOOD), SUITE[0]).status, "runner_error")

    def test_task_splits_cannot_overlap_or_be_empty(self):
        with self.assertRaises(ValueError):
            EvalTask("bad", "instruction", (("a", "a"),), (("a", "a"),))
        with self.assertRaises(ValueError):
            replace(SUITE[0], holdout=())

    def test_cli_failure_status_and_output_boundary(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("sys.stdout"),
            patch("sys.stderr"),
        ):
            root = Path(directory)
            (root / "config.json").write_text(BAD)
            self.assertEqual(main(["fixture", str(root)]), 1)
            self.assertEqual(
                main(["fixture", str(root), "--output", str(root / "report.json")]), 2
            )
            (root / "config.json").write_text(GOOD)
            self.assertEqual(main(["fixture", str(root)]), 0)


if __name__ == "__main__":
    unittest.main()
