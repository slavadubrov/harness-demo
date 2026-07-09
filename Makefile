.PHONY: run failures test lint format check

run:
	uv run harness-ablation

failures:
	uv run harness-ablation --show-failures

test:
	uv run python -m unittest discover -s tests -v

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

check: lint format test
