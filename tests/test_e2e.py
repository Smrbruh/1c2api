"""End-to-end tests for the full 1c2api pipeline.

Covers:
  - EDT parsing → Configuration
  - Schema building
  - OpenAPI generation + validation
  - CLI invocation via typer.testing.CliRunner
  - Exit codes
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from generator_openapi.generator import OpenAPIGenerator
from generator_schema.builder import SchemaBuilder
from parser_1c.adapters.edt_parser import EDTParser
from parser_1c.cli import app

# ── Fixture path ──────────────────────────────────────────────────────────────
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SIMPLE_EDT = FIXTURES_DIR / "simple-edt"


# ─────────────────────────────────────────────────────────────────────────────
#  Test 1: Full pipeline from EDT directory
# ─────────────────────────────────────────────────────────────────────────────
class TestFullPipelineFromEDT:
    """Parse EDT → schemas → OpenAPI and verify every layer."""

    def test_parser_finds_nomenklatura_catalog(self) -> None:
        """EDTParser must find the Номенклатура catalog."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        catalog_names = [c.name for c in cfg.catalogs]
        assert "Номенклатура" in catalog_names, (
            f"Expected 'Номенклатура' in catalogs, got: {catalog_names}"
        )

    def test_parser_fields_present(self) -> None:
        """All three attributes must be present on the catalog."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        catalog = next(c for c in cfg.catalogs if c.name == "Номенклатура")
        field_names = [f.name for f in catalog.fields]
        for expected in ("Артикул", "Цена", "Активен"):
            assert expected in field_names, f"Field '{expected}' not found. Got: {field_names}"

    def test_articul_is_required(self) -> None:
        """Артикул has FillChecking=FillIfNotFilled so required must be True."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        catalog = next(c for c in cfg.catalogs if c.name == "Номенклатура")
        articul = next(f for f in catalog.fields if f.name == "Артикул")
        assert articul.required is True, "Артикул.required should be True"

    def test_schema_builder_produces_item_and_input(self) -> None:
        """SchemaBuilder must create NomenklaturaItem and NomenklaturaInput."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        assert "NomenklaturaItem" in schemas, f"Keys: {list(schemas)}"
        assert "NomenklaturaInput" in schemas, f"Keys: {list(schemas)}"

    def test_item_schema_has_id_field(self) -> None:
        """NomenklaturaItem must include the _id field."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        item = schemas["NomenklaturaItem"]
        assert "_id" in item["properties"], "NomenklaturaItem must have '_id' property"

    def test_input_schema_has_no_id_field(self) -> None:
        """NomenklaturaInput must NOT include _id (write-only payload)."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        inp = schemas["NomenklaturaInput"]
        assert "_id" not in inp["properties"], "NomenklaturaInput must not have '_id'"

    def test_openapi_version(self) -> None:
        """OpenAPI spec must declare version 3.0.3."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        spec = OpenAPIGenerator(cfg, schemas).generate_dict()
        assert spec["openapi"] == "3.0.3"

    def test_openapi_paths_include_catalog_routes(self) -> None:
        """OpenAPI spec must include collection and item paths for Номенклатура."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        spec = OpenAPIGenerator(cfg, schemas).generate_dict()
        paths = spec["paths"]
        assert "/catalogs/Номенклатура" in paths, f"Paths: {list(paths)}"
        assert "/catalogs/Номенклатура/{id}" in paths, f"Paths: {list(paths)}"

    def test_openapi_post_endpoint_exists(self) -> None:
        """POST /catalogs/Номенклатура must be present."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        spec = OpenAPIGenerator(cfg, schemas).generate_dict()
        assert "post" in spec["paths"]["/catalogs/Номенклатура"]

    def test_openapi_components_schemas(self) -> None:
        """NomenklaturaItem must be registered in components/schemas."""
        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        spec = OpenAPIGenerator(cfg, schemas).generate_dict()
        assert "NomenklaturaItem" in spec["components"]["schemas"]

    def test_openapi_spec_is_valid(self) -> None:
        """The generated OpenAPI spec must pass openapi-spec-validator."""
        from openapi_spec_validator import validate

        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        spec = OpenAPIGenerator(cfg, schemas).generate_dict()
        # validate() raises if invalid
        validate(spec)


# ─────────────────────────────────────────────────────────────────────────────
#  Test 2: CLI generates all output files
# ─────────────────────────────────────────────────────────────────────────────
class TestCLIGeneratesAllFiles:
    """Invoke the CLI and verify output files are created correctly."""

    def test_cli_creates_all_files(self, tmp_path: Path) -> None:
        """CLI with --format all must produce openapi.yaml, postman, and markdown."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            [str(SIMPLE_EDT), "--output", str(tmp_path), "--format", "all"],
        )
        assert result.exit_code == 0, (
            f"CLI exited with code {result.exit_code}.\nOutput:\n{result.output}"
        )

        assert (tmp_path / "openapi.yaml").exists(), "openapi.yaml not found"
        assert (tmp_path / "postman_collection.json").exists(), "postman_collection.json not found"
        assert (tmp_path / "api_docs.md").exists(), "api_docs.md not found"

    def test_openapi_yaml_content(self, tmp_path: Path) -> None:
        """Generated openapi.yaml must declare openapi: '3.0.3'."""
        runner = CliRunner()
        runner.invoke(
            app,
            [str(SIMPLE_EDT), "--output", str(tmp_path), "--format", "all"],
        )
        spec = yaml.safe_load((tmp_path / "openapi.yaml").read_text(encoding="utf-8"))
        assert spec.get("openapi") == "3.0.3"

    def test_postman_collection_contains_nomenklatura(self, tmp_path: Path) -> None:
        """Postman collection must contain a folder named 'Номенклатура'."""
        runner = CliRunner()
        runner.invoke(
            app,
            [str(SIMPLE_EDT), "--output", str(tmp_path), "--format", "all"],
        )
        collection = json.loads((tmp_path / "postman_collection.json").read_text(encoding="utf-8"))
        folder_names = [item["name"] for item in collection.get("item", [])]
        assert "Номенклатура" in folder_names, (
            f"'Номенклатура' not in Postman folders: {folder_names}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Test 3: OpenAPI spec validation via file round-trip
# ─────────────────────────────────────────────────────────────────────────────
class TestOpenAPISpecIsValid:
    """Round-trip the spec through YAML and validate with openapi-spec-validator."""

    def test_yaml_roundtrip_valid(self) -> None:
        """Spec written to disk and re-read must still pass validation."""
        from openapi_spec_validator import validate
        from openapi_spec_validator.readers import read_from_filename

        cfg = EDTParser(SIMPLE_EDT).parse()
        schemas = SchemaBuilder(cfg).build()
        yaml_content = OpenAPIGenerator(cfg, schemas).generate_yaml()

        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(yaml_content)
            tmp_path = fh.name

        try:
            spec, _ = read_from_filename(tmp_path)
            validate(spec)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Test 4: CLI exit codes
# ─────────────────────────────────────────────────────────────────────────────
class TestCLIExitCodes:
    """Verify correct exit codes for valid and invalid inputs."""

    def test_nonexistent_path_exits_1(self, tmp_path: Path) -> None:
        """CLI must exit with code 1 when the source path does not exist."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            [str(tmp_path / "does_not_exist"), "--output", str(tmp_path / "out")],
        )
        assert result.exit_code == 1, (
            f"Expected exit code 1 for missing path, got {result.exit_code}"
        )

    def test_valid_edt_path_exits_0(self, tmp_path: Path) -> None:
        """CLI must exit with code 0 for a valid EDT source directory."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            [str(SIMPLE_EDT), "--output", str(tmp_path / "out")],
        )
        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}.\nOutput:\n{result.output}"
        )
