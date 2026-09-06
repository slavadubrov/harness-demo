"""Optional OpenAI transport: buffer output; never dispatch partial candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .grader import SCHEMA


class ProviderFailure(Exception):
    def __init__(
        self,
        code: str,
        *,
        request_id: str | None = None,
        response_id: str | None = None,
        partial_output: bool = False,
        parameter: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.request_id = request_id
        self.response_id = response_id
        self.partial_output = partial_output
        self.parameter = parameter


@dataclass(frozen=True)
class Reply:
    text: str
    output: list[dict[str, Any]]
    model: str
    response_id: str
    request_id: str | None
    input_tokens: int
    output_tokens: int


class OpenAIProvider:
    def __init__(self, api_key: str) -> None:
        from openai import OpenAI

        # No SDK retries: an uncertain request is a recorded failure, not free work.
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            max_retries=0,
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def generate(self, request: dict[str, Any]) -> Reply:
        """Preserve output items for reasoning retention, but omit them from reports."""
        from openai import APIError

        partial = False
        response_id = None
        request_id = None
        completed = None
        try:
            with self.client.responses.create(**request, stream=True) as stream:
                request_id = stream.response.headers.get("x-request-id")
                for event in stream:
                    data = event.model_dump(exclude_unset=True)
                    kind = data["type"]
                    if kind == "response.output_text.delta":
                        partial = True
                    elif kind == "response.created":
                        response_id = data["response"]["id"]
                    elif kind in {"error", "response.failed", "response.incomplete"}:
                        error = (
                            data.get("error")
                            or data.get("response", {}).get("error")
                            or data
                        )
                        raise ProviderFailure(
                            str(error.get("code", kind)),
                            request_id=request_id,
                            response_id=response_id,
                            partial_output=partial,
                        )
                    elif kind == "response.completed":
                        completed = data["response"]
            if completed is None or completed.get("status") != "completed":
                raise ProviderFailure("missing_completion")
            output = completed["output"]
            content = [
                part
                for item in output
                if item["type"] == "message"
                for part in item["content"]
            ]
            if any(part["type"] == "refusal" for part in content):
                raise ProviderFailure("refusal")
            text = "".join(
                part["text"] for part in content if part["type"] == "output_text"
            )
            if not text:
                raise ProviderFailure("empty_output")
            usage = completed.get("usage")
            if not usage:
                raise ProviderFailure("missing_usage")
            return Reply(
                text,
                output,
                completed["model"],
                completed["id"],
                request_id,
                usage["input_tokens"],
                usage["output_tokens"],
            )
        except ProviderFailure as exc:
            exc.request_id = exc.request_id or request_id
            exc.response_id = exc.response_id or response_id
            exc.partial_output = exc.partial_output or partial
            raise
        except APIError as exc:
            raise ProviderFailure(
                str(exc.code or type(exc).__name__),
                parameter=exc.param,
                request_id=getattr(exc, "request_id", request_id),
                response_id=response_id,
                partial_output=partial,
            ) from None
        except Exception as exc:
            # Do not log provider exception messages: they may contain request data.
            raise ProviderFailure(
                type(exc).__name__,
                request_id=request_id,
                response_id=response_id,
                partial_output=partial,
            ) from None


def response_format() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "normalizer",
            "strict": True,
            "schema": SCHEMA,
        }
    }
