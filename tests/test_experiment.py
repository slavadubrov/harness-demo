"""Run real grading with scripted providers; no credentials or network needed."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_ablation.experiment import Settings, run_experiment
from harness_ablation.provider import ProviderFailure, Reply
from harness_ablation.suite import SUITE

GOOD = '{"strip":true,"case":"lower","separator":"-"}'
BAD = '{"strip":false,"case":"preserve","separator":"preserve"}'


def reply(text):
    return Reply(
        text,
        [
            {"type": "reasoning", "encrypted_content": "opaque"},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
        "test-snapshot",
        "resp_test",
        "req_test",
        10,
        20,
    )


class ExperimentTests(unittest.TestCase):
    def test_only_feedback_changes_and_holdout_never_sent(self):
        requests = []

        def generate(request):
            requests.append(request)
            feedback = request["input"][-1]["content"]
            return reply(GOOD if "Public check result" in feedback else BAD)

        with tempfile.TemporaryDirectory() as directory:
            report = run_experiment(
                (SUITE[0],), Settings("test"), generate, Path(directory) / "result.json"
            )
        self.assertEqual(len(requests), 4)
        self.assertEqual(
            [row["status"] for row in report["trials"]], ["failed", "passed"]
        )
        self.assertEqual(report["output_tokens"], 80)
        self.assertEqual(report["summary"]["paired"]["treatment_wins"], 1)
        self.assertEqual(requests[0], requests[2])
        self.assertEqual(requests[1]["input"][:-1], requests[3]["input"][:-1])
        self.assertIn("opaque", str(requests[1]))
        for text, _ in SUITE[0].holdout:
            if text:
                self.assertNotIn(text, str(requests))
        self.assertEqual(report["compaction"], "disabled")

    def test_provider_intervention_stops_all_dispatch_and_counts_missing_trials(self):
        for failed_call in (1, 2):
            calls = []

            def generate(request, calls=calls, failed_call=failed_call):
                calls.append(request)
                if len(calls) == failed_call:
                    raise ProviderFailure(
                        "misalignment_policy_violation",
                        request_id="req_block",
                        response_id="resp_block",
                        partial_output=True,
                    )
                return reply(GOOD)

            with tempfile.TemporaryDirectory() as directory:
                report = run_experiment(
                    (SUITE[0],),
                    Settings("test", trials=2),
                    generate,
                    Path(directory) / "result.json",
                )
            self.assertEqual(len(calls), failed_call)
            self.assertEqual(report["status"], "stopped")
            self.assertFalse(report["usage_known"])
            self.assertEqual(report["summary"]["paired"]["ties"], 0)
            self.assertEqual(report["summary"]["paired"]["excluded_pairs"], 2)
            self.assertEqual(report["trials"][0]["status"], "provider_failure")
            self.assertEqual(report["summary"]["blind-retry"]["planned"], 2)
            self.assertEqual(report["summary"]["blind-retry"]["passed"], 0)
            self.assertTrue(
                all(
                    row["status"] == "not_run_after_provider_failure"
                    for row in report["trials"][1:]
                )
            )

    def test_interrupted_run_never_persists_example_pass_as_final_pass(self):
        import json

        calls = 0

        def generate(request):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return reply(GOOD)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with self.assertRaises(KeyboardInterrupt):
                run_experiment((SUITE[0],), Settings("test"), generate, output)
            report = json.loads(output.read_text())
        self.assertEqual(report["status"], "running")
        self.assertEqual(report["trials"][0]["status"], "awaiting_final")
        self.assertEqual(calls, 2)

    def test_drop_reasoning_is_separate_from_compaction(self):
        requests = []

        def generate(request):
            requests.append(request)
            return reply(GOOD)

        with tempfile.TemporaryDirectory() as directory:
            run_experiment(
                (SUITE[0],),
                Settings("test", retain_reasoning=False),
                generate,
                Path(directory) / "result.json",
            )
        self.assertNotIn("include", requests[0])
        self.assertNotIn("encrypted_content", str(requests[1]))

    def test_budget_and_empty_suite_rejected_before_dispatch(self):
        for kwargs in (
            {"trials": 0},
            {"trials": 11},
            {"max_output_tokens": 0},
            {"max_output_tokens": 5000},
            {"reasoning_effort": "unknown"},
        ):
            with self.assertRaises(ValueError):
                Settings("test", **kwargs)
        with (
            patch("harness_ablation.experiment.write_json") as write,
            self.assertRaises(ValueError),
        ):
            run_experiment(
                (), Settings("test"), lambda _: reply(GOOD), Path("unused.json")
            )
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
