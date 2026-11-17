.PHONY: install lint format test run dry-run digest status test-destinations clean

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

test:
	pytest

run:
	ai-visibility-tracker run

dry-run:
	ai-visibility-tracker run --dry-run

digest:
	ai-visibility-tracker digest --dry-run

status:
	ai-visibility-tracker status

test-destinations:
	ai-visibility-tracker test-destinations

clean:
	rm -rf build dist src/*.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
