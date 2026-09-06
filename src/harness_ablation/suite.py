"""Versioned tiny tasks: public examples for feedback, held-out cases for scoring."""

from dataclasses import asdict, dataclass

from .artifacts import digest, json_bytes


@dataclass(frozen=True)
class EvalTask:
    name: str
    instruction: str
    examples: tuple[tuple[str, str], ...]
    holdout: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (
            not self.name
            or not self.instruction
            or not self.examples
            or not self.holdout
        ):
            raise ValueError("Tasks require a name, instruction, examples and holdout")
        inputs = [text for text, _ in self.examples + self.holdout]
        if len(set(inputs)) != len(inputs):
            raise ValueError("Example and holdout inputs must be unique and disjoint")

    @property
    def sha256(self) -> str:
        return digest(json_bytes(asdict(self)))


SUITE = (
    EvalTask(
        "slug",
        "Make lowercase slugs. Collapse whitespace to hyphens; trim outer whitespace.",
        ((" Hello WORLD ", "hello-world"), ("Two   Words", "two-words")),
        (("\tMIXED\nCase ", "mixed-case"), ("", ""), (" Café ", "café")),
    ),
    EvalTask(
        "label",
        "Trim outer whitespace and uppercase labels. Preserve internal whitespace.",
        ((" hello ", "HELLO"), ("Two  Words", "TWO  WORDS")),
        (("\tMixed case\n", "MIXED CASE"), ("", ""), (" Straße ", "STRASSE")),
    ),
    EvalTask(
        "identifier",
        "Preserve letter case; collapse whitespace to underscores without outer space.",
        ((" Hello World ", "Hello_World"), ("Two   Words", "Two_Words")),
        (("\tMiXeD\nCase ", "MiXeD_Case"), ("", ""), (" Café ", "Café")),
    ),
)
