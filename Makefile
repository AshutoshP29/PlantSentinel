# Linux/macOS entry point. On Windows use: .\make.ps1 <target>
.PHONY: setup lint format test seed demo-check offline-check

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

seed:
	uv run python scripts/seed_demo.py --reset $(ARGS)

demo-check:
	uv run --offline python scripts/demo_check.py $(ARGS)

# Run with Wi-Fi OFF: container isolation, then the full demo through the gateway.
offline-check:
	docker compose exec -T backend python /app/scripts/check_isolation.py
	uv run --offline python scripts/demo_check.py $(ARGS)
