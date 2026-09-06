"""Trusted standalone grader. It interprets JSON data and never imports a candidate.

Run by runner.py with isolated Python and a minimal environment. Keep this file
stdlib-only so the exact bytes can be copied and hashed before execution.
"""

from __future__ import annotations

import json
import sys

SCHEMA = {
    "type": "object",
    "properties": {
        "strip": {"type": "boolean"},
        "case": {"type": "string", "enum": ["preserve", "lower", "upper"]},
        "separator": {"type": "string", "enum": ["preserve", "-", "_"]},
    },
    "required": ["strip", "case", "separator"],
    "additionalProperties": False,
}


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_config(text: str) -> dict[str, object]:
    config = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(config, dict) or set(config) != {"strip", "case", "separator"}:
        raise ValueError("Expected only strip, case and separator")
    if type(config["strip"]) is not bool:
        raise ValueError("strip must be a boolean")
    if config["case"] not in ("preserve", "lower", "upper"):
        raise ValueError("Invalid case operation")
    if config["separator"] not in ("preserve", "-", "_"):
        raise ValueError("Invalid separator")
    return config


def normalize(text: str, config: dict[str, object]) -> str:
    if config["strip"]:
        text = text.strip()
    if config["case"] == "lower":
        text = text.lower()
    elif config["case"] == "upper":
        text = text.upper()
    separator = config["separator"]
    if separator != "preserve":
        # ponytail: whitespace-only DSL; add operations only with new task cases.
        text = str(separator).join(text.split())
    return text


def main() -> int:
    payload = json.load(sys.stdin)
    try:
        config = parse_config(payload["config"])
    except (ValueError, TypeError, RecursionError):
        print(
            json.dumps({"schema": False, "passed": 0, "total": len(payload["cases"])})
        )
        return 1
    cases = payload["cases"]
    passed = sum(normalize(text, config) == expected for text, expected in cases)
    print(json.dumps({"schema": True, "passed": passed, "total": len(cases)}))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
