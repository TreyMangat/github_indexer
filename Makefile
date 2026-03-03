PYTHON ?= python

.PHONY: install dev lint typecheck test fmt run

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check .

fmt:
	ruff format .

typecheck:
	mypy src

test:
	pytest

run:
	repo-recall serve --host 0.0.0.0 --port 8080
