.PHONY: install run test test-cov lint format demo clean help

# Default target
.DEFAULT_GOAL := help

# ─────────────────────────────────────────────
#  Variables
# ─────────────────────────────────────────────
CONFIG ?= tests/fixtures/simple-edt
PYTHON  = python
PIP     = pip

# ─────────────────────────────────────────────
#  Targets
# ─────────────────────────────────────────────

## install: install project in editable mode with dev dependencies
install:
	$(PIP) install -e ".[dev]"

## run: parse CONFIG path and write output to ./api  (override: make run CONFIG=./path)
run:
	$(PYTHON) -m parser_1c $(CONFIG) --output ./api

## test: run test suite
test:
	pytest tests/ -v

## test-cov: run tests with coverage report
test-cov:
	pytest \
	  --cov=parser_1c \
	  --cov=generator_schema \
	  --cov=generator_openapi \
	  --cov=generator_postman \
	  --cov=generator_markdown \
	  --cov-report=term-missing \
	  tests/

## lint: run ruff linter and format check
lint:
	ruff check .
	ruff format --check .

## format: auto-format all Python files
format:
	ruff format .

## demo: generate sample output from fixture EDT project
demo:
	$(PYTHON) -m parser_1c tests/fixtures/simple-edt --output ./demo-output
	@echo ""
	@echo "✓  Demo output written to ./demo-output/"
	@ls -lh demo-output/

## clean: remove build artifacts, cache files, and generated output
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -f .coverage coverage.xml
	rm -rf demo-output/ api/ ci-output/ .pytest_cache/ dist/ build/ *.egg-info/
	@echo "✓  Cleaned."

## help: show this help message
help:
	@echo "Usage: make <target>"
	@echo ""
	@grep -E '^## ' Makefile | sed 's/^## /  /'
