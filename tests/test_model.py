"""Regression tests for the deterministic ablation lab."""

from __future__ import annotations

import unittest

from harness_ablation.model import (
    CONFIGS,
    TASKS,
    failures_for_config,
    run_suite,
    run_task,
    summarize,
    validate_reference_expectations,
)


class HarnessAblationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.results = run_suite()
        self.rows = summarize(self.results)

    def test_reference_expectations_hold(self) -> None:
        validate_reference_expectations(self.rows)

    def test_summary_has_expected_ablation_shape(self) -> None:
        by_name = {row.config: row for row in self.rows}

        self.assertEqual([row.passed for row in self.rows], [1, 2, 5, 12])
        self.assertEqual(by_name["full-harness"].total, len(TASKS))
        self.assertGreater(
            by_name["full-harness"].avg_simulated_tokens,
            by_name["bare-loop"].avg_simulated_tokens,
        )

    def test_retry_adds_one_attempt_for_flaky_task(self) -> None:
        task = next(task for task in TASKS if task.name == "fix-parser-edge-case")
        bare = next(config for config in CONFIGS if config.name == "bare-loop")
        retry = next(config for config in CONFIGS if config.name == "retry-only")

        bare_result = run_task(task, bare)
        retry_result = run_task(task, retry)

        self.assertFalse(bare_result.passed)
        self.assertIn("flaky tool call was not retried", bare_result.failure_reasons)
        self.assertTrue(retry_result.passed)
        self.assertEqual(retry_result.attempts, bare_result.attempts + 1)

    def test_full_harness_has_no_failed_tasks(self) -> None:
        failures = failures_for_config(self.results, "full-harness")

        self.assertEqual(failures, ())


if __name__ == "__main__":
    unittest.main()
