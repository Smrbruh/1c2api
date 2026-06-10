# Contributing to 1c2api

Thank you for your interest in contributing to **1c2api** — the open-source tool that parses 1C:Enterprise configurations and generates OpenAPI specs, Postman collections, Markdown docs, and Swagger UI.

---

## Quick Start for Developers

```bash
# 1. Clone the repository
git clone https://github.com/bakdaulet/1c2api.git
cd 1c2api

# 2. Install in editable mode with all dev dependencies
pip install -e ".[dev]"

# 3. Run the demo to verify everything works
make demo
# → creates ./demo-output/ with openapi.yaml, postman_collection.json, api_docs.md, swagger_ui.html
```

---

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `parser_1c/` | Core: CLI entry point, Pydantic models, parser adapters |
| `parser_1c/adapters/` | `EDTParser` (XML directories), `CFAdapter` (binary .cf files) |
| `generator_schema/` | Builds JSON Schema Draft-07 from parsed models |
| `generator_openapi/` | Generates OpenAPI 3.0.3 YAML with full CRUD + pagination |
| `generator_postman/` | Generates Postman Collection v2.1 JSON |
| `generator_markdown/` | Generates Markdown API Reference |
| `swagger_ui/` | Generates a self-contained Swagger UI HTML page |
| `tests/` | Pytest test suite |
| `tests/fixtures/` | Sample EDT project used by tests and `make demo` |

---

## How to Add a New Generator

Follow these four steps:

**Step 1.** Create a new package directory at the repo root:
```
generator_myformat/
    __init__.py
    generator.py
```

**Step 2.** Implement a generator class in `generator.py`. It must accept a `Configuration` object (and optionally a `schemas` dict) and expose a `generate()` or `generate_dict()` method:
```python
from parser_1c.models import Configuration

class MyFormatGenerator:
    def __init__(self, config: Configuration) -> None:
        self.config = config

    def generate(self) -> str:
        ...
```

**Step 3.** Register the new format in `parser_1c/cli.py` inside the `_write_output()` function, following the existing `if want_all or fmt == "openapi":` pattern.

**Step 4.** Add the package name to `pyproject.toml` under `[tool.setuptools.packages.find] include`.

---

## Running Tests

```bash
# Run all tests
make test

# Run tests with coverage report
make test-cov

# Run a single test file
pytest tests/test_e2e.py -v

# Run a single test method
pytest tests/test_e2e.py::TestFullPipelineFromEDT::test_openapi_spec_is_valid -v
```

Coverage must stay at or above **70 %**. The CI pipeline enforces this.

---

## Linting and Formatting

This project uses **ruff** for both linting and formatting.

```bash
# Check for lint errors
make lint

# Auto-fix formatting
make format
```

The CI pipeline runs both checks on every push and pull request. PRs with lint failures will not be merged.

---

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature or generator |
| `fix:` | Bug fix |
| `docs:` | Documentation changes only |
| `test:` | Adding or updating tests |
| `refactor:` | Code restructuring without behaviour change |
| `chore:` | Tooling, CI, dependency updates |

Examples:
```
feat: add Excel (xlsx) generator
fix: handle missing Synonym tag in EDT parser
docs: update CONTRIBUTING with Excel generator steps
test: add E2E test for CFAdapter
```

---

## Creating a Pull Request

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-new-generator
   ```

2. Make your changes, add tests, and ensure everything passes:
   ```bash
   make lint
   make test
   ```

3. Push your branch and open a PR against `main`.

4. Fill in the PR description:
   - **What** was changed
   - **Why** it is needed
   - Link to any related issue

5. Wait for CI to go green. All checks must pass before merge.

---

## Roadmap

See the [Roadmap section in README.md](README.md#roadmap) for planned features, or open an [issue](https://github.com/bakdaulet/1c2api/issues) to propose a new one.
