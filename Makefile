# Linux/macOS entry point. On Windows use: .\make.ps1 <target>
.PHONY: setup lint format test hooks

setup:
	uv sync --group dev
	uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest -m "not integration"

# seed, dev, up, offline-check: added in later build steps
