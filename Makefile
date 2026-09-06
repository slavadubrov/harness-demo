.PHONY: run failures fixtures test lint format typecheck check

UV = uv run --locked --extra live

run:
	uv run --locked harness-ablation

failures:
	uv run --locked harness-ablation --show-failures

fixtures:
	uv run --locked harness-eval fixture fixtures/passing

# Development checks install the optional SDK to exercise its mocked transport.
# They never load .env or make API calls.
test:
	$(UV) python -m unittest discover -s tests -v

lint:
	$(UV) ruff check .

format:
	$(UV) ruff format --check .

typecheck:
	$(UV) mypy src

check: lint format typecheck test
