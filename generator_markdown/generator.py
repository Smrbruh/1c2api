"""
generator_markdown/generator.py — Markdown API Reference генератор.

Принимает OpenAPI 3.0 dict и строит полный человекочитаемый
Markdown-документ в стиле GitHub-совместимого API Reference.

Структура документа
--------------------
# {title}
> {description}

## Содержание           ← auto-generated TOC
## Авторизация          ← если есть securitySchemes
## Schemas              ← компонентные схемы с полями
## {TagName}            ← секция на каждый тег
### {summary}           ← заголовок операции
  - Метод и путь
  - Описание
  - Параметры (таблица)
  - Тело запроса (таблица полей + JSON-пример)
  - Ответы (таблица статус/описание + JSON-примеры)
---
*Сгенерировано 1C2API*
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from parser_1c.openapi_utils import collect_operations, deref, example_from_schema

logger = logging.getLogger(__name__)

OADict = dict[str, Any]

# HTTP методы → эмодзи-бейдж для Markdown
_METHOD_BADGE: dict[str, str] = {
    "GET":    "![GET](https://img.shields.io/badge/GET-61affe?style=flat-square)",
    "POST":   "![POST](https://img.shields.io/badge/POST-49cc90?style=flat-square)",
    "PUT":    "![PUT](https://img.shields.io/badge/PUT-fca130?style=flat-square)",
    "PATCH":  "![PATCH](https://img.shields.io/badge/PATCH-50e3c2?style=flat-square)",
    "DELETE": "![DELETE](https://img.shields.io/badge/DELETE-f93e3e?style=flat-square)",
    "HEAD":   "![HEAD](https://img.shields.io/badge/HEAD-9012fe?style=flat-square)",
}

_HTTP_EMOJI: dict[str, str] = {
    "GET": "🔵", "POST": "🟢", "PUT": "🟡",
    "PATCH": "🟠", "DELETE": "🔴", "HEAD": "⚪",
}


# ---------------------------------------------------------------------------
# Утилиты для Markdown
# ---------------------------------------------------------------------------

def _md_escape(text: str) -> str:
    """Экранировать символы, специальные для Markdown таблиц."""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", "")


def _md_code(text: str, lang: str = "") -> str:
    """Обернуть в code-fence."""
    return f"```{lang}\n{text}\n```"


def _anchor(text: str) -> str:
    """Сгенерировать GitHub-совместимый якорь из строки."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    return slug


def _type_label(schema: OADict) -> str:
    """Кратко описать тип JSON Schema: 'string (uuid)', 'array[object]' и т.п."""
    if not schema:
        return "any"
    
    # Обработка allOf
    if "allOf" in schema:
        first = schema["allOf"][0] if schema["allOf"] else {}
        return _type_label(first)
    
    t = schema.get("type", "")
    fmt = schema.get("format", "")
    ref = schema.get("$ref", "")

    if ref:
        return ref.split("/")[-1]
    if t == "array":
        items = schema.get("items", {})
        inner = _type_label(items) if items else "any"
        return f"array[{inner}]"
    if fmt:
        return f"{t} ({fmt})"
    return t or "any"


# ---------------------------------------------------------------------------
# Секция: схемы компонентов
# ---------------------------------------------------------------------------

def _render_schema_table(schema: OADict, spec: OADict) -> str:
    """Отрендерить таблицу свойств JSON Schema."""
    resolved = deref(schema, spec)
    props = resolved.get("properties", {})
    required = set(resolved.get("required", []))

    if not props:
        return "_Схема не содержит свойств._\n"

    lines = [
        "| Поле | Тип | Обяз. | Описание |",
        "|------|-----|:-----:|----------|",
    ]
    for name, prop in props.items():
        resolved_prop = deref(prop, spec) if "$ref" in prop else prop
        type_str = _type_label(resolved_prop)
        req = "✓" if name in required else ""
        desc = _md_escape(resolved_prop.get("description") or resolved_prop.get("title") or "")
        readonly = " `readonly`" if resolved_prop.get("readOnly") else ""
        lines.append(f"| `{_md_escape(name)}` | `{type_str}`{readonly} | {req} | {desc} |")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Секция: параметры операции
# ---------------------------------------------------------------------------

def _render_params_table(params: list[OADict], spec: OADict) -> str:
    """Отрендерить таблицу параметров операции."""
    if not params:
        return ""

    lines = [
        "| Параметр | Где | Тип | Обяз. | По умолч. | Описание |",
        "|----------|-----|-----|:-----:|-----------|----------|",
    ]
    for p in params:
        resolved = deref(p, spec) if "$ref" in p else p
        name = resolved.get("name", "?")
        location = resolved.get("in", "")
        schema = resolved.get("schema", {})
        type_str = _type_label(deref(schema, spec) if "$ref" in schema else schema)
        required = "✓" if resolved.get("required") else ""
        default = _md_escape(str(schema.get("default", "")))
        desc = _md_escape(resolved.get("description", ""))
        lines.append(
            f"| `{_md_escape(name)}` | `{location}` | `{type_str}` | {required} | {default} | {desc} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Секция: тело запроса
# ---------------------------------------------------------------------------

def _render_request_body(req_body: OADict, spec: OADict) -> str:
    """Отрендерить секцию Request Body."""
    if not req_body:
        return ""

    content = req_body.get("content", {})
    json_content = content.get("application/json", {})
    if not json_content:
        return ""

    schema = deref(json_content.get("schema", {}), spec)
    lines: list[str] = [
        "",
        "**Тело запроса** (`application/json`)",
        "",
    ]

    # Таблица полей
    lines.append(_render_schema_table(schema, spec))

    # JSON пример
    example_data = example_from_schema(schema, spec)
    if example_data is None:
        example_data = {}
    example = example_data
    
    lines += [
        "**Пример:**",
        "",
        _md_code(json.dumps(example, ensure_ascii=False, indent=2), "json"),
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Секция: ответы
# ---------------------------------------------------------------------------

def _render_responses(responses: OADict, spec: OADict) -> str:
    """Отрендерить таблицу ответов + примеры для 2xx."""
    if not responses:
        return ""

    lines: list[str] = [
        "",
        "**Ответы:**",
        "",
        "| Код | Описание |",
        "|-----|----------|",
    ]
    for code, resp_obj in sorted(responses.items()):
        resolved = deref(resp_obj, spec) if "$ref" in resp_obj else resp_obj
        desc = _md_escape(resolved.get("description", ""))
        lines.append(f"| `{code}` | {desc} |")

    lines.append("")

    # JSON-примеры для 2xx
    for code, resp_obj in sorted(responses.items()):
        if not str(code).startswith("2"):
            continue
        resolved = deref(resp_obj, spec) if "$ref" in resp_obj else resp_obj
        content = resolved.get("content", {})
        json_content = content.get("application/json", {})
        if not json_content:
            continue
        schema = deref(json_content.get("schema", {}), spec)
        example_data = example_from_schema(schema, spec)
        if example_data is None:
            example_data = {}
        example = example_data
        
        lines += [
            f"<details><summary>Пример ответа {code}</summary>",
            "",
            _md_code(json.dumps(example, ensure_ascii=False, indent=2), "json"),
            "",
            "</details>",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Публичный класс
# ---------------------------------------------------------------------------

class MarkdownGenerator:
    """Генератор Markdown API Reference из OpenAPI 3.0 спецификации.

    Usage::

        spec = yaml.safe_load(Path("openapi.yaml").read_text())
        md   = MarkdownGenerator(spec).generate()
        Path("API_REFERENCE.md").write_text(md, encoding="utf-8")

    Args:
        spec:              OpenAPI 3.0 dict.
        include_toc:       Добавить авто-содержание.
        include_schemas:   Добавить секцию со схемами компонентов.
        include_badges:    Использовать shield.io бейджи для методов.
    """

    def __init__(
        self,
        spec: OADict,
        *,
        include_toc: bool = True,
        include_schemas: bool = True,
        include_badges: bool = False,
    ) -> None:
        self._spec = spec
        self._include_toc = include_toc
        self._include_schemas = include_schemas
        self._include_badges = include_badges

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def generate(self) -> str:
        """Сгенерировать Markdown API Reference как строку.

        Returns:
            Строка Markdown, готовая к записи в файл.
        """
        sections: list[str] = []

        sections.append(self._render_header())

        if self._include_toc:
            sections.append(self._render_toc())

        if self._include_schemas:
            schemas_section = self._render_schemas_section()
            if schemas_section:
                sections.append(schemas_section)

        sections.append(self._render_operations())
        sections.append(self._render_footer())

        return "\n\n".join(s for s in sections if s)

    # ------------------------------------------------------------------
    # Секции документа
    # ------------------------------------------------------------------

    def _render_header(self) -> str:
        info = self._spec.get("info", {})
        title   = info.get("title", "API Reference")
        version = info.get("version", "")
        desc    = info.get("description", "")
        contact = info.get("contact", {})

        lines = [f"# {title}"]
        if version:
            lines.append(f"\n**Версия:** `{version}`")
        if desc:
            lines.append(f"\n> {desc}")

        servers = self._spec.get("servers", [])
        if servers:
            lines.append("\n**Серверы:**\n")
            for s in servers:
                srv_url  = s.get("url", "")
                srv_desc = s.get("description", "")
                lines.append(f"- `{srv_url}` — {srv_desc}")

        if contact.get("url"):
            lines.append(f"\n📎 [{contact.get('name', 'Репозиторий')}]({contact['url']})")

        return "\n".join(lines)

    def _render_toc(self) -> str:
        """Автоматически сгенерировать содержание."""
        grouped = collect_operations(self._spec)
        tag_order = [t["name"] for t in self._spec.get("tags", [])]
        for tag in grouped:
            if tag not in tag_order:
                tag_order.append(tag)

        lines = ["## Содержание", ""]

        if self._include_schemas:
            schemas = self._spec.get("components", {}).get("schemas", {})
            if schemas:
                lines.append("- [Схемы данных](#схемы-данных)")

        for tag in tag_order:
            if tag not in grouped:
                continue
            lines.append(f"- [{tag}](#{_anchor(tag)})")
            for path, method, op, _ in grouped[tag]:
                name = op.get("summary") or f"{method.upper()} {path}"
                anchor = _anchor(f"{method}-{path}")
                lines.append(f"  - [{method.upper()} {path}](#{anchor})")

        return "\n".join(lines)

    def _render_schemas_section(self) -> str:
        """Секция со схемами из components/schemas."""
        schemas = self._spec.get("components", {}).get("schemas", {})
        if not schemas:
            return ""

        lines = ["## Схемы данных", ""]

        for name, schema in schemas.items():
            if name == "Error":
                continue
            resolved = deref(schema, self._spec)
            title = resolved.get("title") or name
            desc  = resolved.get("description", "")
            lines += [
                f"### `{name}`",
                "",
                f"_{desc}_" if desc else "",
                "",
                _render_schema_table(resolved, self._spec),
            ]

        if "Error" in schemas:
            resolved = deref(schemas["Error"], self._spec)
            lines += [
                "### `Error` — Стандартная ошибка",
                "",
                _render_schema_table(resolved, self._spec),
            ]

        return "\n".join(lines)

    def _render_operations(self) -> str:
        """Основная секция: операции, сгруппированные по тегам."""
        grouped = collect_operations(self._spec)
        tag_order = [t["name"] for t in self._spec.get("tags", [])]
        for tag in grouped:
            if tag not in tag_order:
                tag_order.append(tag)

        tag_descriptions = {
            t["name"]: t.get("description", "")
            for t in self._spec.get("tags", [])
        }

        sections: list[str] = []

        for tag in tag_order:
            if tag not in grouped:
                continue

            tag_lines: list[str] = [f"## {tag}"]
            if tag_descriptions.get(tag):
                tag_lines.append(f"\n{tag_descriptions[tag]}")
            tag_lines.append("")

            for path, method, operation, path_item in grouped[tag]:
                tag_lines.append(self._render_operation(path, method, operation, path_item))

            sections.append("\n".join(tag_lines))

        return "\n\n---\n\n".join(sections)

    def _render_operation(
        self,
        path: str,
        method: str,
        operation: OADict,
        path_item: OADict,
    ) -> str:
        """Отрендерить одну операцию."""
        method_upper = method.upper()
        summary = operation.get("summary", f"{method_upper} {path}")
        desc    = operation.get("description", "")
        op_id   = operation.get("operationId", "")

        anchor = _anchor(f"{method}-{path}")
        if self._include_badges:
            badge = _METHOD_BADGE.get(method_upper, method_upper)
            title_line = f"### {badge} `{path}` <a id=\"{anchor}\"></a>"
        else:
            emoji = _HTTP_EMOJI.get(method_upper, "⚪")
            title_line = f"### {emoji} `{method_upper}` `{path}`"

        lines: list[str] = [
            title_line,
            "",
            f"**{summary}**" if summary != f"{method_upper} {path}" else "",
        ]

        if op_id:
            lines.append(f"\n`operationId: {op_id}`")

        if desc:
            lines.append(f"\n{desc}")

        all_params_raw = (
            list(path_item.get("parameters", []))
            + list(operation.get("parameters", []))
        )
        if all_params_raw:
            lines += [
                "",
                "**Параметры:**",
                "",
                _render_params_table(all_params_raw, self._spec),
            ]

        req_body = operation.get("requestBody", {})
        if req_body:
            lines.append(_render_request_body(req_body, self._spec))

        responses = operation.get("responses", {})
        if responses:
            lines.append(_render_responses(responses, self._spec))

        lines.append("")
        return "\n".join(line for line in lines if line is not None)

    def _render_footer(self) -> str:
        return (
            "---\n\n"
            "*Документация сгенерирована автоматически с помощью "
            "[1C2API](https://github.com/your-org/1c2api)*"
        )
