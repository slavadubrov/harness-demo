"""Synthetic task suite and pure functions for the harness-ablation lab.

The module deliberately does not call an LLM, a tool API, or a benchmark. Each
task has declared failure conditions so readers can inspect an ablation method
without mistaking simulated output for production-agent evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import mean

COMPONENT_FIELDS: tuple[str, ...] = (
    "progress_handoff",
    "evaluator",
    "retry_policy",
    "fail_closed_acceptance",
    "context_reset",
)


@dataclass(frozen=True)
class Task:
    """A synthetic task with explicit conditions that can block success."""

    name: str
    difficulty: int
    needs_progress_file: bool = False
    needs_fresh_evaluator: bool = False
    flaky_tool: bool = False
    ambiguous_done: bool = False

    def __post_init__(self) -> None:
        if (
            not self.name
            or type(self.difficulty) is not int
            or not 1 <= self.difficulty <= 5
        ):
            raise ValueError("Task needs a name and integer difficulty from 1 to 5")
        for field in (
            "needs_progress_file",
            "needs_fresh_evaluator",
            "flaky_tool",
            "ambiguous_done",
        ):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be boolean")


@dataclass(frozen=True)
class HarnessConfig:
    """A small set of harness choices to add or remove in an ablation."""

    name: str
    progress_handoff: bool = False
    evaluator: bool = False
    retry_policy: bool = False
    fail_closed_acceptance: bool = False
    context_reset: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Configuration needs a name")
        if any(type(getattr(self, field)) is not bool for field in COMPONENT_FIELDS):
            raise ValueError("Harness switches must be boolean")


@dataclass(frozen=True)
class RunResult:
    """The simulated result of one task under one harness configuration."""

    task: str
    config: str
    passed: bool
    attempts: int
    simulated_tokens: int
    failure_reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        """Return a display-friendly explanation without losing structured data."""

        return "ok" if self.passed else "; ".join(self.failure_reasons)


@dataclass(frozen=True)
class SummaryRow:
    """Aggregate metrics for one configuration over a fixed task suite."""

    config: str
    passed: int
    total: int
    success_rate: float
    avg_attempts: float
    avg_simulated_tokens: float


@dataclass(frozen=True)
class AblationPair:
    """A control/treatment pair that changes one named harness component."""

    component: str
    control: HarnessConfig
    treatment: HarnessConfig


@dataclass(frozen=True)
class PairSummary:
    """Outcome summary for one validated single-component comparison."""

    component: str
    control: str
    treatment: str
    control_passed: int
    treatment_passed: int
    total: int


TASKS: tuple[Task, ...] = (
    Task("rename-api-field", 1),
    Task("fix-parser-edge-case", 2, flaky_tool=True),
    Task("add-cli-flag", 2, ambiguous_done=True),
    Task("repair-css-regression", 3, needs_fresh_evaluator=True),
    Task("split-large-module", 4, needs_progress_file=True),
    Task("migrate-config-format", 4, needs_progress_file=True, flaky_tool=True),
    Task("wire-browser-test", 3, needs_fresh_evaluator=True, ambiguous_done=True),
    Task(
        "multi-file-refactor", 5, needs_progress_file=True, needs_fresh_evaluator=True
    ),
    Task("resume-after-context-loss", 5, needs_progress_file=True, ambiguous_done=True),
    Task("stabilize-flaky-test", 3, flaky_tool=True, ambiguous_done=True),
    Task("implement-importer", 4, needs_progress_file=True, flaky_tool=True),
    Task("finish-polished-ui", 5, needs_fresh_evaluator=True, ambiguous_done=True),
)

CONFIGS: tuple[HarnessConfig, ...] = (
    HarnessConfig("bare-loop"),
    HarnessConfig("retry-only", retry_policy=True),
    HarnessConfig("handoff-and-retry", progress_handoff=True, retry_policy=True),
    HarnessConfig(
        "full-harness",
        progress_handoff=True,
        evaluator=True,
        retry_policy=True,
        fail_closed_acceptance=True,
        context_reset=True,
    ),
)

FULL_HARNESS = CONFIGS[-1]

ABLATION_PAIRS: tuple[AblationPair, ...] = tuple(
    AblationPair(
        component,
        replace(
            FULL_HARNESS,
            name=f"without-{component.replace('_', '-')}",
            **{component: False},
        ),
        FULL_HARNESS,
    )
    for component in (
        "retry_policy",
        "progress_handoff",
        "evaluator",
        "fail_closed_acceptance",
        "context_reset",
    )
)


def changed_components(
    control: HarnessConfig, treatment: HarnessConfig
) -> tuple[str, ...]:
    """Return the component fields whose values differ between two variants."""

    return tuple(
        field
        for field in COMPONENT_FIELDS
        if getattr(control, field) != getattr(treatment, field)
    )


def validate_ablation_pairs(
    pairs: tuple[AblationPair, ...] = ABLATION_PAIRS,
) -> None:
    """Reject comparisons that change zero or multiple harness components."""

    for pair in pairs:
        changed = changed_components(pair.control, pair.treatment)
        if changed != (pair.component,):
            message = (
                f"{pair.component} pair must change only {pair.component}; "
                f"changed {changed or 'nothing'}"
            )
            raise AssertionError(message)


def run_task(task: Task, config: HarnessConfig) -> RunResult:
    """Run one deterministic task and record each unmet harness assumption."""

    attempts = 1
    simulated_tokens = 850 + task.difficulty * 260
    failures: list[str] = []

    if task.flaky_tool:
        if config.retry_policy:
            attempts += 1
            simulated_tokens += 180
        else:
            failures.append("flaky tool call was not retried")

    if task.needs_progress_file:
        if config.progress_handoff:
            simulated_tokens += 220
        else:
            failures.append("next session lost task state")

    if task.needs_progress_file and task.difficulty >= 5:
        if config.context_reset:
            simulated_tokens += 300
        else:
            failures.append("compaction preserved stale assumptions")

    if task.needs_fresh_evaluator:
        if config.evaluator:
            simulated_tokens += 420
        else:
            failures.append("self-review missed an implementation gap")

    if task.ambiguous_done:
        if config.fail_closed_acceptance:
            simulated_tokens += 110
        else:
            failures.append("ambiguous acceptance defaulted to pass")

    return RunResult(
        task=task.name,
        config=config.name,
        passed=not failures,
        attempts=attempts,
        simulated_tokens=simulated_tokens,
        failure_reasons=tuple(failures),
    )


def validate_suite(tasks: tuple[Task, ...], configs: tuple[HarnessConfig, ...]) -> None:
    for label, names in (
        ("tasks", [task.name for task in tasks]),
        ("configs", [config.name for config in configs]),
    ):
        if not names or len(set(names)) != len(names):
            raise ValueError(f"{label} must be nonempty and uniquely named")


def run_suite(
    tasks: tuple[Task, ...] = TASKS,
    configs: tuple[HarnessConfig, ...] = CONFIGS,
) -> tuple[RunResult, ...]:
    """Run every task against every configuration in a stable order."""

    validate_suite(tasks, configs)
    return tuple(run_task(task, config) for config in configs for task in tasks)


def summarize(
    results: tuple[RunResult, ...],
    configs: tuple[HarnessConfig, ...] = CONFIGS,
) -> tuple[SummaryRow, ...]:
    """Summarize a complete result set without hiding simulated metrics."""

    names = [config.name for config in configs]
    if not names or len(set(names)) != len(names):
        raise ValueError("Configurations must be nonempty and uniquely named")
    if set(result.config for result in results) != set(names):
        raise ValueError("Results must match the requested configurations")
    task_sets = []
    for name in names:
        tasks = [result.task for result in results if result.config == name]
        if len(set(tasks)) != len(tasks):
            raise ValueError("Duplicate task results")
        task_sets.append(set(tasks))
    if any(tasks != task_sets[0] for tasks in task_sets):
        raise ValueError("Configurations must be evaluated on the same tasks")
    rows: list[SummaryRow] = []
    for config in configs:
        subset = tuple(result for result in results if result.config == config.name)
        if not subset:
            message = f"No results found for configuration: {config.name}"
            raise ValueError(message)

        rows.append(
            SummaryRow(
                config=config.name,
                passed=sum(result.passed for result in subset),
                total=len(subset),
                success_rate=sum(result.passed for result in subset) / len(subset),
                avg_attempts=mean(result.attempts for result in subset),
                avg_simulated_tokens=mean(result.simulated_tokens for result in subset),
            )
        )
    return tuple(rows)


def summarize_ablation_pairs(
    tasks: tuple[Task, ...] = TASKS,
    pairs: tuple[AblationPair, ...] = ABLATION_PAIRS,
) -> tuple[PairSummary, ...]:
    """Summarize validated leave-one-component-out comparisons."""

    validate_suite(tasks, (FULL_HARNESS,))
    validate_ablation_pairs(pairs)
    rows: list[PairSummary] = []
    for pair in pairs:
        control_passed = sum(run_task(task, pair.control).passed for task in tasks)
        treatment_passed = sum(run_task(task, pair.treatment).passed for task in tasks)
        rows.append(
            PairSummary(
                component=pair.component,
                control=pair.control.name,
                treatment=pair.treatment.name,
                control_passed=control_passed,
                treatment_passed=treatment_passed,
                total=len(tasks),
            )
        )
    return tuple(rows)


def validate_reference_expectations(
    rows: tuple[SummaryRow, ...], task_count: int = len(TASKS)
) -> None:
    """Assert the teaching lab still demonstrates the intended ablation shape."""

    by_name = {row.config: row for row in rows}
    bare = by_name["bare-loop"]
    full = by_name["full-harness"]

    if full.passed != task_count:
        message = "full-harness should pass every synthetic task"
        raise AssertionError(message)
    if full.success_rate <= bare.success_rate:
        message = "full-harness should outperform bare-loop"
        raise AssertionError(message)
    if full.avg_simulated_tokens <= bare.avg_simulated_tokens:
        message = "full-harness should show the simulated cost trade-off"
        raise AssertionError(message)


def failures_for_config(
    results: tuple[RunResult, ...], config_name: str
) -> tuple[RunResult, ...]:
    """Return failed task results for one named configuration."""

    return tuple(
        result
        for result in results
        if result.config == config_name and not result.passed
    )
