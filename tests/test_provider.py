"""Exercise actual SDK streaming decoding with an in-memory HTTP transport."""

import importlib.util
import json
import unittest

from harness_ablation.provider import OpenAIProvider, ProviderFailure


@unittest.skipUnless(
    importlib.util.find_spec("openai"), "Install --extra live for SDK tests"
)
class ProviderTests(unittest.TestCase):
    def call(self, events=None, *, blocked=False):
        import httpx
        from openai import OpenAI

        calls = []

        def handle(request):
            calls.append(request)
            if blocked:
                return httpx.Response(
                    403,
                    headers={"x-request-id": "req_block"},
                    json={
                        "error": {
                            "type": "invalid_request_error",
                            "code": "misalignment_policy_violation",
                            "message": "blocked",
                        }
                    },
                )
            body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "x-request-id": "req_stream",
                },
                text=body,
            )

        provider = object.__new__(OpenAIProvider)
        provider.client = OpenAI(
            api_key="test-only",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        try:
            return provider.generate({"model": "test", "input": "hello"}), calls
        finally:
            provider.close()

    def test_pre_stream_intervention_retains_request_id(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.call(blocked=True)
        self.assertEqual(caught.exception.code, "misalignment_policy_violation")
        self.assertEqual(caught.exception.request_id, "req_block")
        self.assertFalse(caught.exception.partial_output)

    def test_partial_output_then_intervention_is_never_a_candidate(self):
        events = [
            {"type": "response.created", "response": {"id": "resp_partial"}},
            {"type": "response.output_text.delta", "delta": "{}"},
            {"type": "error", "code": "misalignment_policy_violation"},
        ]
        with self.assertRaises(ProviderFailure) as caught:
            self.call(events)
        self.assertEqual(caught.exception.code, "misalignment_policy_violation")
        self.assertEqual(caught.exception.response_id, "resp_partial")
        self.assertTrue(caught.exception.partial_output)

    def test_disconnect_without_completed_event_fails(self):
        with self.assertRaises(ProviderFailure) as caught:
            self.call([{"type": "response.output_text.delta", "delta": "{}"}])
        self.assertEqual(caught.exception.code, "missing_completion")
        self.assertTrue(caught.exception.partial_output)

    def test_complete_response_extracts_usage_and_output(self):
        response = {
            "id": "resp_done",
            "status": "completed",
            "model": "test-snapshot",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "{}"}],
                }
            ],
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        }
        result, calls = self.call(
            [{"type": "response.completed", "response": response}]
        )
        self.assertEqual(result.text, "{}")
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output, response["output"])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
