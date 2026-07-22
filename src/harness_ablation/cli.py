"""Command-line interface for the harness-ablation teaching lab."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from time import perf_counter

from .model import (
    CONFIGS,
    failures_for_config,
    run_suite,
    summarize,
    summarize_ablation_pairs,
    validate_ablation_pairs,
    validate_reference_expectations,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without mixing presentation with simulation logic."""

    parser = argparse.ArgumentParser(
        description="Run a deterministic teaching lab for harness ablations."
    )
    parser.add_argument(
        "--show-failures",
        action="store_true",
        help="print the named synthetic failure reasons for every configuration",
    )
    return parser


def print_tables() -> None:
    """Print the cumulative matrix and valid single-component comparisons."""

    results = run_suite()
    rows = summarize(results)
    validate_reference_expectations(rows)

    print("Cumulative harness matrix (synthetic teaching lab)")
    print("config             passed  success  avg_attempts  avg_simulated_tokens")
    print("-----------------  ------  -------  ------------  --------------------")
    for row in rows:
        print(
            f"{row.config:<17}  "
            f"{row.passed:>2}/{row.total:<3}   "
            f"{row.success_rate:>6.0%}  "
            f"{row.avg_attempts:>12.2f}  "
            f"{row.avg_simulated_tokens:>20.0f}"
        )

    validate_ablation_pairs()
    print("\nLeave-one-component-out ablations")
    print("component                 control  treatment  delta")
    print("-----------------------  -------  ---------  -----")
    for row in summarize_ablation_pairs():
        delta = row.treatment_passed - row.control_passed
        print(
            f"{row.component:<23}  "
            f"{row.control_passed:>2}/{row.total:<2}    "
            f"{row.treatment_passed:>2}/{row.total:<2}      "
            f"{delta:>+3}"
        )


def print_failures() -> None:
    """Show why the simulated configurations fail instead of hiding the mechanism."""

    results = run_suite()
    print("\nSynthetic failure matrix")
    for config in CONFIGS:
        failed = failures_for_config(results, config.name)
        if not failed:
            print(f"\n{config.name}: all synthetic tasks pass")
            continue

        print(f"\n{config.name}:")
        for result in failed:
            print(f"- {result.task}: {result.reason}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lab and return a process status for the console-script entry point."""

    started = perf_counter()
    args = build_parser().parse_args(argv)
    print_tables()
    if args.show_failures:
        print_failures()
    print(f"\nSmoke check passed in {perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
