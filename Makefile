.PHONY: install run test lint

install:
	pip install -e ".[dev]"

run:
	python -m parser_1c.cli $(CONFIG) --output ./api

test:
	pytest tests/ -v

lint:
	ruff check parser_1c/
