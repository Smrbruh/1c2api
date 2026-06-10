"""
1C2API CLI — точка входа командной строки.

Использование
-------------
Прямой запуск::

    python -m parser_1c.cli ./my-edt-export --output ./api --format openapi
    python -m parser_1c.cli ./MyConfig.cf   --output ./api --format all

Через ``make``::

    make run CONFIG=./my-config

Поддерживаемые форматы вывода
------------------------------
- ``openapi``  — OpenAPI 3.0.3 YAML спецификация (валидный, с CRUD)
- ``postman``  — Postman Collection v2.1 JSON
- ``markdown`` — человекочитаемая документация в Markdown
- ``all``      — все три формата сразу
"""

from __future__ import annotations

import json
import logging
import shutil
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.theme import Theme

from parser_1c.adapters.base import ParseError
from parser_1c.models import Configuration

# ---------------------------------------------------------------------------
# Rich консоль
# ---------------------------------------------------------------------------

_THEME = Theme(
    {
        "info":    "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error":   "bold red",
        "dim":     "dim white",
        "accent":  "bold magenta",
    }
)

console     = Console(theme=_THEME)
err_console = Console(stderr=True, theme=_THEME)


# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=err_console, show_time=False, show_path=False)],
    )


# ---------------------------------------------------------------------------
# Enum форматов
# ---------------------------------------------------------------------------

class OutputFormat(str, Enum):
    OPENAPI  = "openapi"
    POSTMAN  = "postman"
    MARKDOWN = "markdown"
    ALL      = "all"


# ---------------------------------------------------------------------------
# Определение типа источника
# ---------------------------------------------------------------------------

def _detect_source(config_path: Path) -> str:
    """Определить тип источника по пути.

    Returns:
        ``"cf"`` для .cf файлов, ``"edt"`` для директорий.

    Raises:
        typer.BadParameter: Если тип не распознан.
    """
    if config_path.is_file() and config_path.suffix.lower() == ".cf":
        return "cf"
    if config_path.is_dir():
        return "edt"
    raise typer.BadParameter(
        f"Не удалось определить тип конфигурации: {config_path}\n"
        "Ожидается .cf файл или папка EDT выгрузки."
    )


# ---------------------------------------------------------------------------
# Генераторы выходных форматов
# ---------------------------------------------------------------------------

def _generate_openapi(cfg: Configuration, output_dir: Path) -> Path:
    """Сгенерировать OpenAPI 3.0.3 YAML через SchemaBuilder + OpenAPIGenerator."""
    import yaml
    from generator_schema.builder import SchemaBuilder
    from generator_openapi.generator import OpenAPIGenerator

    schemas  = SchemaBuilder(cfg).build()
    yaml_str = OpenAPIGenerator(cfg, schemas).generate()

    out = output_dir / "openapi.yaml"
    out.write_text(yaml_str, encoding="utf-8")
    return out


def _generate_postman(cfg: Configuration, output_dir: Path) -> Path:
    """Сгенерировать Postman Collection v2.1 JSON."""
    items = []
    for catalog in cfg.catalogs:
        items.append({
            "name": f"GET /catalogs/{catalog.name}",
            "request": {
                "method": "GET",
                "header": [],
                "url": {
                    "raw": f"{{{{baseUrl}}}}/catalogs/{catalog.name}",
                    "host": ["{{baseUrl}}"],
                    "path": ["catalogs", catalog.name],
                },
                "description": catalog.synonym or catalog.name,
            },
        })

    collection = {
        "info": {
            "name": "1C Configuration API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "_postman_id": "1c2api-generated",
            "description": "Автоматически сгенерировано 1C2API",
        },
        "variable": [{"key": "baseUrl", "value": "http://localhost:8000"}],
        "item": items,
    }

    out = output_dir / "postman_collection.json"
    out.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _generate_markdown(cfg: Configuration, output_dir: Path) -> Path:
    """Сгенерировать Markdown документацию."""
    lines: list[str] = [
        "# 1C Configuration API — Документация\n",
        "> Автоматически сгенерировано [1C2API](https://github.com/Smrbruh/1c2api)\n",
        "---\n",
        "## Справочники (Catalogs)\n",
    ]

    if not cfg.catalogs:
        lines.append("_Справочники не найдены._\n")
    else:
        for catalog in cfg.catalogs:
            lines.append(f"### `{catalog.name}` — {catalog.synonym}\n")
            if catalog.fields:
                lines.append("**Реквизиты:**\n")
                lines.append("| Имя | Синоним | Тип | Обязательный | Описание |")
                lines.append("|-----|---------|-----|:------------:|----------|")
                for f in catalog.fields:
                    req = "✅" if f.required else ""
                    lines.append(
                        f"| `{f.name}` | {f.alias} | `{f.type.value}` | {req} | {f.description} |"
                    )
                lines.append("")
            for ts in catalog.tabular_sections:
                lines.append(f"**Табличная часть `{ts.name}`:**\n")
                if ts.fields:
                    lines.append("| Имя | Тип | Обязательный |")
                    lines.append("|-----|-----|:------------:|")
                    for f in ts.fields:
                        req = "✅" if f.required else ""
                        lines.append(f"| `{f.name}` | `{f.type.value}` | {req} |")
                lines.append("")

    if cfg.documents:
        lines.append("## Документы (Documents)\n")
        for doc in cfg.documents:
            lines.append(f"### `{doc.name}` — {doc.synonym}\n")

    if cfg.enums:
        lines.append("## Перечисления (Enums)\n")
        for enum in cfg.enums:
            lines.append(f"### `{enum.name}` — {enum.synonym}\n")
            if enum.values:
                for v in enum.values:
                    lines.append(f"- `{v.name}` — {v.synonym}")
            lines.append("")

    out = output_dir / "api_docs.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Rich вывод
# ---------------------------------------------------------------------------

def _print_summary(cfg: Configuration) -> None:
    table = Table(
        title="📦 Разобранная конфигурация",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Тип объекта",  style="bold",    min_width=20)
    table.add_column("Кол-во",       justify="right", style="accent")
    table.add_column("Примеры",      style="dim")

    def _examples(items, attr: str = "name") -> str:
        names = [getattr(i, attr) for i in items[:3]]
        suffix = ", …" if len(items) > 3 else ""
        return ", ".join(names) + suffix if names else "—"

    table.add_row("Справочники (Catalogs)",   str(len(cfg.catalogs)),  _examples(cfg.catalogs))
    table.add_row("Документы (Documents)",    str(len(cfg.documents)), _examples(cfg.documents))
    table.add_row("Перечисления (Enums)",     str(len(cfg.enums)),     _examples(cfg.enums))
    table.add_row("Реквизиты (всего)",        str(sum(len(c.fields) for c in cfg.catalogs)), "")
    table.add_row("Табличных частей (всего)", str(sum(len(c.tabular_sections) for c in cfg.catalogs)), "")

    console.print()
    console.print(table)


def _print_outputs(files: list[tuple[str, Path]]) -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("icon",   style="success", width=3)
    table.add_column("format", style="bold",    min_width=12)
    table.add_column("path",   style="dim")

    icons = {"openapi": "📄", "postman": "📮", "markdown": "📝"}
    for fmt, path in files:
        table.add_row(icons.get(fmt, "📁"), fmt.upper(), str(path))

    console.print(table)


# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="1c2api",
    help="Парсит конфигурации 1C и генерирует OpenAPI / Postman / Markdown.",
    add_completion=False,
    rich_markup_mode="rich",
)


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Argument(help="Путь к EDT-папке или .cf файлу конфигурации.", show_default=False),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Папка для результатов."),
    ] = Path("./api"),
    format: Annotated[  # noqa: A002
        OutputFormat,
        typer.Option("--format", "-f", help="Формат выходных файлов.", case_sensitive=False),
    ] = OutputFormat.ALL,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Включить DEBUG логирование."),
    ] = False,
    executable_1c: Annotated[
        str,
        typer.Option("--1cv8", help="Путь к 1cv8.exe (только для .cf файлов)."),
    ] = "1cv8.exe",
) -> None:
    """Разобрать конфигурацию 1C и сгенерировать документацию/спецификации.

    \b
    Примеры:
      1c2api ./my-edt-export
      1c2api ./MyConfig.cf --output ./dist --format openapi
      1c2api ./my-config   --format markdown --verbose
    """
    _setup_logging(verbose)

    console.print(Panel.fit(
        "[bold cyan]1C2API[/bold cyan] — генератор OpenAPI из конфигураций 1C",
        border_style="cyan", padding=(0, 2),
    ))

    # Валидация входных данных
    config = config.expanduser().resolve()
    if not config.exists():
        err_console.print(f"[error]Путь не найден:[/error] {config}")
        raise typer.Exit(code=1)

    source_type = _detect_source(config)
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    # Разбор конфигурации
    cfg: Configuration | None = None
    cf_dump_dir: Path | None = None  # папка EDT-выгрузки из .cf (для очистки)

    with Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TaskProgressColumn(), TimeElapsedColumn(),
        console=console, transient=True,
    ) as progress:

        parse_task = progress.add_task("[cyan]Разбор конфигурации…", total=None)

        try:
            if source_type == "edt":
                from parser_1c.adapters.edt_parser import EDTParser
                progress.update(parse_task, description="[cyan]EDT: читаю XML файлы…")
                cfg = EDTParser(config).parse()

            else:  # "cf"
                from parser_1c.adapters.cf_adapter import CFAdapter
                progress.update(parse_task, description="[cyan]CF: RestoreIB…")
                # Папка для EDT-выгрузки — временная внутри output
                cf_dump_dir = output / "_edt_dump"
                cfg = CFAdapter(
                    config,
                    output_dir=cf_dump_dir,
                    executable_1c=executable_1c,
                ).parse()

        except ParseError as exc:
            err_console.print(f"\n[error]Ошибка разбора:[/error] {exc}")
            raise typer.Exit(code=2) from exc
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"\n[error]Неожиданная ошибка:[/error] {exc}")
            if verbose:
                import traceback
                err_console.print(traceback.format_exc())
            raise typer.Exit(code=3) from exc

        progress.update(parse_task, completed=1, total=1, description="[success]Разбор завершён")

    # Убираем временную EDT-выгрузку из output (пользователю она не нужна)
    if cf_dump_dir and cf_dump_dir.exists():
        shutil.rmtree(cf_dump_dir, ignore_errors=True)

    # cfg гарантированно заполнен — все ветки либо присваивают cfg, либо делают Exit
    _print_summary(cfg)  # type: ignore[arg-type]

    # Генерация выходных файлов
    formats_to_run: list[OutputFormat] = (
        [OutputFormat.OPENAPI, OutputFormat.POSTMAN, OutputFormat.MARKDOWN]
        if format == OutputFormat.ALL
        else [format]
    )

    generated: list[tuple[str, Path]] = []

    with Progress(
        SpinnerColumn(spinner_name="dots2"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), TaskProgressColumn(),
        console=console, transient=True,
    ) as progress:
        gen_task = progress.add_task("[cyan]Генерация файлов…", total=len(formats_to_run))

        for fmt in formats_to_run:
            progress.update(gen_task, description=f"[cyan]Генерирую {fmt.value}…")
            try:
                if fmt == OutputFormat.OPENAPI:
                    try:
                        import yaml  # noqa: F401
                    except ImportError:
                        err_console.print(
                            "[warning]PyYAML не установлен, пропускаю openapi.[/warning] "
                            "Установите: pip install pyyaml"
                        )
                        progress.advance(gen_task)
                        continue
                    path = _generate_openapi(cfg, output)  # type: ignore[arg-type]
                    generated.append(("openapi", path))

                elif fmt == OutputFormat.POSTMAN:
                    path = _generate_postman(cfg, output)  # type: ignore[arg-type]
                    generated.append(("postman", path))

                elif fmt == OutputFormat.MARKDOWN:
                    path = _generate_markdown(cfg, output)  # type: ignore[arg-type]
                    generated.append(("markdown", path))

            except Exception as exc:  # noqa: BLE001
                err_console.print(f"[warning]Не удалось сгенерировать {fmt.value}:[/warning] {exc}")

            progress.advance(gen_task)

    console.print()
    console.rule("[success]Готово[/success]")
    _print_outputs(generated)
    console.print(f"\n[success]✓[/success] Результаты сохранены в [bold]{output}[/bold]\n")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> None:
    """Внешняя точка входа (используется в pyproject.toml scripts)."""
    app()


if __name__ == "__main__":
    main()
