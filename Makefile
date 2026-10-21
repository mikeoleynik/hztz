.PHONY: setup test lint build

setup:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run mypy src

build:
	uv build
