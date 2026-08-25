.PHONY: dev install test

install:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

dev:
	.venv/bin/uvicorn app.main:app --reload --port 8420

test:
	.venv/bin/pytest -q
