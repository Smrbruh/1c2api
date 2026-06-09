"""
Тесты для CFAdapter и CLI.

Тесты CFAdapter:
  - mock subprocess.run (1cv8.exe не нужен)
  - проверка правильных аргументов команд
  - обработка ошибок: нулевой returncode, таймаут, отсутствие 1cv8.exe

Тесты CLI:
  - детектирование типа источника (.cf / директория)
  - успешный запуск с EDT фикстурой
  - правильные exit codes при ошибках
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from typer.testing import CliRunner

from parser_1c.adapters.base import ParseError
from parser_1c.cli import OutputFormat, _detect_source, app

# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "simple-edt"

runner = CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# CFAdapter — тесты subprocess логики
# ---------------------------------------------------------------------------

class TestCFAdapter:
    """Тесты CFAdapter без реального 1cv8.exe (mock subprocess)."""

    @pytest.fixture()
    def cf_file(self, tmp_path: Path) -> Path:
        """Создать фиктивный .cf файл."""
        p = tmp_path / "TestConfig.cf"
        p.write_bytes(b"\x00" * 16)  # минимальное содержимое
        return p

    @pytest.fixture()
    def edt_output(self, tmp_path: Path) -> Path:
        """Подготовить папку EDT с минимальной фикстурой."""
        edt_dir = tmp_path / "edt_out"
        catalogs = edt_dir / "Catalogs"
        catalogs.mkdir(parents=True)
        # Копируем реальную фикстуру
        import shutil
        shutil.copy(
            FIXTURE_DIR / "Catalogs" / "Номенклатура.mdo",
            catalogs / "Номенклатура.mdo",
        )
        return edt_dir

    def _make_good_result(self) -> MagicMock:
        """subprocess.CompletedProcess с rc=0."""
        r = MagicMock(spec=subprocess.CompletedProcess)
        r.returncode = 0
        r.stderr = b""
        r.stdout = b""
        return r

    # -- корректный happy path -----------------------------------------------

    def test_calls_restore_ib_with_correct_args(
        self, cf_file: Path, edt_output: Path
    ) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        with patch("subprocess.run", return_value=self._make_good_result()) as mock_run:
            with patch.object(
                CFAdapter, "_step_dump_config",
                side_effect=lambda *, temp_db, output_dir: None,
            ):
                with patch("parser_1c.adapters.cf_adapter.EDTParser") as mock_edt:
                    mock_edt.return_value.parse.return_value = MagicMock()
                    CFAdapter(cf_file, output_dir=edt_output).parse()

            first_call_args = mock_run.call_args_list[0][0][0]
            assert first_call_args[0] == "1cv8.exe"
            assert first_call_args[1] == "DESIGNER"
            assert "/RestoreIB" in first_call_args
            assert str(cf_file) in first_call_args
            # /F<path> без пробела
            f_args = [a for a in first_call_args if a.startswith("/F")]
            assert len(f_args) == 1

    def test_calls_dump_config_with_correct_args(
        self, cf_file: Path, edt_output: Path
    ) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        call_args_list: list = []

        def fake_run(args, **kwargs):
            call_args_list.append(args)
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            with patch("parser_1c.adapters.cf_adapter.EDTParser") as mock_edt:
                mock_edt.return_value.parse.return_value = MagicMock()
                CFAdapter(cf_file, output_dir=edt_output).parse()

        assert len(call_args_list) == 2
        dump_args = call_args_list[1]
        assert dump_args[0] == "1cv8.exe"
        assert "/DumpConfigToFiles" in dump_args
        assert str(edt_output) in dump_args

    def test_temp_db_deleted_on_success(self, cf_file: Path, edt_output: Path) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        created_temp_dbs: list[Path] = []

        def fake_run(args, **kwargs):
            # Выясняем temp_db по /F<path>
            for a in args:
                if a.startswith("/F"):
                    p = Path(a[2:])
                    if p not in created_temp_dbs:
                        created_temp_dbs.append(p)
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            with patch("parser_1c.adapters.cf_adapter.EDTParser") as mock_edt:
                mock_edt.return_value.parse.return_value = MagicMock()
                CFAdapter(cf_file, output_dir=edt_output).parse()

        # temp_db должна быть удалена после разбора
        for p in created_temp_dbs:
            assert not p.exists(), f"temp_db не удалена: {p}"

    def test_temp_db_deleted_on_failure(self, cf_file: Path, edt_output: Path) -> None:
        """Temp DB удаляется даже при исключении в subprocess."""
        from parser_1c.adapters.cf_adapter import CFAdapter

        created_dirs: list[Path] = []
        real_mkdir = Path.mkdir

        def tracking_mkdir(self_path, **kw):  # noqa: ANN001
            real_mkdir(self_path, **kw)
            if "_1c2api_tmpdb_" in self_path.name:
                created_dirs.append(self_path)

        bad_result = MagicMock()
        bad_result.returncode = 1
        bad_result.stderr = b"fake error"
        bad_result.stdout = b""

        with patch("subprocess.run", return_value=bad_result):
            with patch.object(Path, "mkdir", tracking_mkdir):
                with pytest.raises(ParseError):
                    CFAdapter(cf_file, output_dir=edt_output).parse()

        for d in created_dirs:
            assert not d.exists(), f"temp_db не удалена после ошибки: {d}"

    # -- обработка ошибок -----------------------------------------------------

    def test_raises_parse_error_on_nonzero_returncode(
        self, cf_file: Path, edt_output: Path
    ) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        bad = MagicMock()
        bad.returncode = 1
        bad.stderr = b"1C: configuration not found"
        bad.stdout = b""

        with patch("subprocess.run", return_value=bad):
            with pytest.raises(ParseError, match="returncode 1"):
                CFAdapter(cf_file, output_dir=edt_output).parse()

    def test_raises_parse_error_when_executable_not_found(
        self, cf_file: Path, edt_output: Path
    ) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            with pytest.raises(ParseError, match="1cv8.exe"):
                CFAdapter(cf_file, output_dir=edt_output).parse()

    def test_raises_parse_error_on_timeout(
        self, cf_file: Path, edt_output: Path
    ) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["1cv8.exe"], timeout=300),
        ):
            with pytest.raises(ParseError, match="[Тт]аймаут"):
                CFAdapter(cf_file, output_dir=edt_output).parse()

    def test_raises_value_error_for_non_cf_file(self, tmp_path: Path) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        not_cf = tmp_path / "config.xml"
        not_cf.write_text("<root/>")
        with pytest.raises(ValueError, match=".cf"):
            CFAdapter(not_cf)

    def test_custom_executable(self, cf_file: Path, edt_output: Path) -> None:
        from parser_1c.adapters.cf_adapter import CFAdapter

        call_args: list = []

        def fake_run(args, **kwargs):
            call_args.extend(args[:2])
            r = MagicMock()
            r.returncode = 0
            r.stderr = b""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            with patch("parser_1c.adapters.cf_adapter.EDTParser") as mock_edt:
                mock_edt.return_value.parse.return_value = MagicMock()
                CFAdapter(
                    cf_file,
                    output_dir=edt_output,
                    executable_1c="/opt/1cv8/bin/1cv8",
                ).parse()

        assert "/opt/1cv8/bin/1cv8" in call_args


# ---------------------------------------------------------------------------
# _detect_source — юнит тесты
# ---------------------------------------------------------------------------

class TestDetectSource:
    def test_detects_cf_file(self, tmp_path: Path) -> None:
        cf = tmp_path / "cfg.cf"
        cf.write_bytes(b"\x00")
        assert _detect_source(cf) == "cf"

    def test_detects_edt_directory(self, tmp_path: Path) -> None:
        assert _detect_source(tmp_path) == "edt"

    def test_raises_for_unknown_file_type(self, tmp_path: Path) -> None:
        import typer

        xml = tmp_path / "config.xml"
        xml.write_text("<root/>")
        with pytest.raises(typer.BadParameter):
            _detect_source(xml)


# ---------------------------------------------------------------------------
# CLI — интеграционные тесты через CliRunner
# ---------------------------------------------------------------------------

class TestCLI:
    """Тесты CLI через Typer CliRunner (без реального 1cv8.exe)."""

    def test_edt_run_succeeds(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [str(FIXTURE_DIR), "--output", str(tmp_path / "out"), "--format", "markdown"],
        )
        assert result.exit_code == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert (tmp_path / "out" / "api_docs.md").exists()

    def test_edt_generates_all_formats(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml", reason="PyYAML не установлен")
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [str(FIXTURE_DIR), "--output", str(out), "--format", "all"],
        )
        assert result.exit_code == 0, result.stdout
        assert (out / "openapi.yaml").exists()
        assert (out / "postman_collection.json").exists()
        assert (out / "api_docs.md").exists()

    def test_edt_generates_postman(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        result = runner.invoke(
            app,
            [str(FIXTURE_DIR), "--output", str(out), "--format", "postman"],
        )
        assert result.exit_code == 0, result.stdout
        assert (out / "postman_collection.json").exists()

    def test_markdown_contains_catalog_name(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        runner.invoke(
            app,
            [str(FIXTURE_DIR), "--output", str(out), "--format", "markdown"],
        )
        md = (out / "api_docs.md").read_text(encoding="utf-8")
        assert "Номенклатура" in md
        assert "Артикул" in md

    def test_postman_contains_catalog_route(self, tmp_path: Path) -> None:
        import json as json_mod

        out = tmp_path / "out"
        runner.invoke(
            app,
            [str(FIXTURE_DIR), "--output", str(out), "--format", "postman"],
        )
        collection = json_mod.loads((out / "postman_collection.json").read_text())
        routes = [item["name"] for item in collection["item"]]
        assert any("Номенклатура" in r for r in routes)

    def test_exit_code_1_for_nonexistent_path(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [str(tmp_path / "nonexistent"), "--format", "markdown"])
        assert result.exit_code == 1

    def test_output_format_enum_values(self) -> None:
        assert set(f.value for f in OutputFormat) == {
            "openapi", "postman", "markdown", "all"
        }

    def test_cf_format_calls_cf_adapter(self, tmp_path: Path) -> None:
        """CLI правильно роутит .cf файл на CFAdapter."""
        cf = tmp_path / "test.cf"
        cf.write_bytes(b"\x00" * 16)

        mock_cfg = MagicMock()
        mock_cfg.catalogs = []
        mock_cfg.documents = []
        mock_cfg.enums = []

        with patch(
            "parser_1c.adapters.cf_adapter.CFAdapter.parse",
            return_value=mock_cfg,
        ) as mock_parse:
            result = runner.invoke(
                app,
                [str(cf), "--output", str(tmp_path / "out"), "--format", "markdown"],
            )

        assert result.exit_code == 0, result.stdout
        mock_parse.assert_called_once()
