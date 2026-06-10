"""
generator_openapi/generator.py — OpenAPI 3.0.3 генератор.

Принимает словарь JSON Schema от :class:`~parser_1c.generator_schema.SchemaBuilder`
и конфигурацию 1С, строит полную OpenAPI 3.0.3 спецификацию с CRUD эндпоинтами.

CRUD маппинг на каждый Catalog
-------------------------------
+------+--------------------------------+--------------------------+
| Verb | Path                           | Описание                 |
+======+================================+==========================+
| GET  | /catalogs/{name}               | Список с пагинацией      |
| POST | /catalogs/{name}               | Создать новый элемент    |
| GET  | /catalogs/{name}/{id}          | Получить по GUID         |
| PATCH| /catalogs/{name}/{id}          | Обновить (partial)       |
|DELETE| /catalogs/{name}/{id}          | Пометить на удаление     |
+------+--------------------------------+--------------------------+

Пагинация (GET список)
    - ``$top``  — сколько вернуть (default 100, max 1000)
    - ``$skip`` — сколько пропустить (default 0)
    - ``$filter`` — строка фильтра в стиле OData

Ответы
    - 200 / 201 / 204 — успех
    - 400 — валидационная ошибка (``#/components/schemas/Error``)
    - 404 — объект не найден
    - 500 — внутренняя ошибка сервера

Схемы в components/schemas
    - ``{Name}Item``  — полная схема объекта (read)
    - ``{Name}Input`` — схема для записи (write)
    - ``Error``       — стандартная ошибка
    - ``PaginatedResponse`` — обёртка для списочных ответов
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from parser_1c.generator_schema.builder import JsonSchema
from parser_1c.models import Configuration

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Транслитерация: кириллица → ASCII (для имён компонентов OpenAPI)
# OpenAPI 3.0 требует: components/schemas propertyNames ^[a-zA-Z0-9._-]+$
# ---------------------------------------------------------------------------

_CYR_TO_LAT: dict[str, str] = {
    "А": "A",  "Б": "B",  "В": "V",  "Г": "G",  "Д": "D",
    "Е": "E",  "Ё": "Yo", "Ж": "Zh", "З": "Z",  "И": "I",
    "Й": "Y",  "К": "K",  "Л": "L",  "М": "M",  "Н": "N",
    "О": "O",  "П": "P",  "Р": "R",  "С": "S",  "Т": "T",
    "У": "U",  "Ф": "F",  "Х": "Kh", "Ц": "Ts", "Ч": "Ch",
    "Ш": "Sh", "Щ": "Shch","Ъ": "",  "Ы": "Y",  "Ь": "",
    "Э": "E",  "Ю": "Yu", "Я": "Ya",
    "а": "a",  "б": "b",  "в": "v",  "г": "g",  "д": "d",
    "е": "e",  "ё": "yo", "ж": "zh", "з": "z",  "и": "i",
    "й": "y",  "к": "k",  "л": "l",  "м": "m",  "н": "n",
    "о": "o",  "п": "p",  "р": "r",  "с": "s",  "т": "t",
    "у": "u",  "ф": "f",  "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch","ъ": "",  "ы": "y",  "ь": "",
    "э": "e",  "ю": "yu", "я": "ya",
}

_TRANSLIT_TABLE = str.maketrans(_CYR_TO_LAT)


def _to_component_name(name: str) -> str:
    """Преобразовать имя 1С в валидный идентификатор компонента OpenAPI.

    OpenAPI 3.0 требует, чтобы ключи в ``components/schemas`` соответствовали
    паттерну ``^[a-zA-Z0-9._-]+$``. Кириллица транслитерируется.

    Args:
        name: Произвольная строка (может содержать кириллицу).

    Returns:
        Строка, содержащая только ``[a-zA-Z0-9._-]``.

    Examples:
        >>> _to_component_name("Номенклатура")
        "Nomenklatura"
    """
    transliterated = name.translate(_TRANSLIT_TABLE)
    safe = "".join(c for c in transliterated if c.isalnum() or c in "._-")
    return safe or "Object"


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

OAS_VERSION = "3.0.3"

# Параметры пагинации — переиспользуются через $ref
_PAGINATION_PARAMS = [
    {
        "$ref": "#/components/parameters/TopParam",
    },
    {
        "$ref": "#/components/parameters/SkipParam",
    },
    {
        "$ref": "#/components/parameters/FilterParam",
    },
]

# Общий path-параметр id
_ID_PARAM_REF = {"$ref": "#/components/parameters/IdParam"}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _ref(schema_name: str) -> dict[str, str]:
    """Вернуть JSON Reference на компонент схемы."""
    return {"$ref": f"#/components/schemas/{schema_name}"}


def _error_response(description: str = "Ошибка") -> dict[str, Any]:
    """Стандартный ответ с ошибкой."""
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": _ref("Error"),
            }
        },
    }


def _json_response(schema: dict[str, Any], description: str = "OK") -> dict[str, Any]:
    """Стандартный успешный JSON ответ."""
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": schema,
            }
        },
    }


def _json_request_body(schema_name: str, required: bool = True) -> dict[str, Any]:
    """requestBody с JSON содержимым."""
    return {
        "required": required,
        "content": {
            "application/json": {
                "schema": _ref(schema_name),
            }
        },
    }


# ---------------------------------------------------------------------------
# CRUD операции
# ---------------------------------------------------------------------------

def _build_list_operation(catalog_name: str, synonym: str) -> dict[str, Any]:
    """GET /catalogs/{name} — список с пагинацией."""
    return {
        "summary": f"Список «{synonym}»",
        "description": (
            f"Возвращает постранично список элементов справочника «{synonym}». "
            f"Используйте параметры `$top` и `$skip` для пагинации."
        ),
        "operationId": f"list{catalog_name}",
        "tags": ["Catalogs"],
        "parameters": _PAGINATION_PARAMS,
        "responses": {
            "200": _json_response(
                schema={
                    "type": "array",
                    "items": _ref(f"{catalog_name}Item"),
                },
                description=f"Массив элементов «{synonym}»",
            ),
            "400": _error_response("Некорректные параметры запроса"),
            "500": _error_response("Внутренняя ошибка сервера"),
        },
    }


def _build_create_operation(catalog_name: str, synonym: str) -> dict[str, Any]:
    """POST /catalogs/{name} — создать новый элемент."""
    return {
        "summary": f"Создать элемент «{synonym}»",
        "description": f"Создаёт новый элемент справочника «{synonym}».",
        "operationId": f"create{catalog_name}",
        "tags": ["Catalogs"],
        "requestBody": _json_request_body(f"{catalog_name}Input"),
        "responses": {
            "201": _json_response(
                schema=_ref(f"{catalog_name}Item"),
                description="Созданный элемент",
            ),
            "400": _error_response("Ошибка валидации входных данных"),
            "500": _error_response("Внутренняя ошибка сервера"),
        },
    }


def _build_get_by_id_operation(catalog_name: str, synonym: str) -> dict[str, Any]:
    """GET /catalogs/{name}/{id} — получить элемент по GUID."""
    return {
        "summary": f"Получить элемент «{synonym}» по ID",
        "description": f"Возвращает один элемент справочника «{synonym}» по его GUID.",
        "operationId": f"get{catalog_name}ById",
        "tags": ["Catalogs"],
        "responses": {
            "200": _json_response(
                schema=_ref(f"{catalog_name}Item"),
                description=f"Элемент «{synonym}»",
            ),
            "404": _error_response(f"Элемент «{synonym}» не найден"),
            "500": _error_response("Внутренняя ошибка сервера"),
        },
    }


def _build_patch_operation(catalog_name: str, synonym: str) -> dict[str, Any]:
    """PATCH /catalogs/{name}/{id} — частичное обновление."""
    return {
        "summary": f"Обновить элемент «{synonym}»",
        "description": (
            f"Частично обновляет элемент справочника «{synonym}». "
            f"Переданные поля перезаписываются, непереданные — остаются без изменений."
        ),
        "operationId": f"patch{catalog_name}",
        "tags": ["Catalogs"],
        "requestBody": _json_request_body(f"{catalog_name}Input", required=False),
        "responses": {
            "200": _json_response(
                schema=_ref(f"{catalog_name}Item"),
                description="Обновлённый элемент",
            ),
            "400": _error_response("Ошибка валидации входных данных"),
            "404": _error_response(f"Элемент «{synonym}» не найден"),
            "500": _error_response("Внутренняя ошибка сервера"),
        },
    }


def _build_delete_operation(catalog_name: str, synonym: str) -> dict[str, Any]:
    """DELETE /catalogs/{name}/{id} — пометить на удаление."""
    return {
        "summary": f"Пометить на удаление «{synonym}»",
        "description": (
            f"Устанавливает пометку удаления на элемент справочника «{synonym}». "
            f"Физического удаления не происходит — объект помечается для последующего удаления."
        ),
        "operationId": f"delete{catalog_name}",
        "tags": ["Catalogs"],
        "responses": {
            "204": {"description": "Пометка удаления установлена"},
            "404": _error_response(f"Элемент «{synonym}» не найден"),
            "500": _error_response("Внутренняя ошибка сервера"),
        },
    }


# ---------------------------------------------------------------------------
# Reusable parameters
# ---------------------------------------------------------------------------

def _build_shared_parameters() -> dict[str, Any]:
    """Общие параметры, выносимые в components/parameters."""
    return {
        "IdParam": {
            "name": "id",
            "in": "path",
            "required": True,
            "description": "GUID объекта в формате UUID",
            "schema": {
                "type": "string",
                "format": "uuid",
            },
        },
        "TopParam": {
            "name": "$top",
            "in": "query",
            "required": False,
            "description": "Максимальное количество возвращаемых элементов (OData $top)",
            "schema": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 100,
            },
        },
        "SkipParam": {
            "name": "$skip",
            "in": "query",
            "required": False,
            "description": "Количество пропускаемых элементов (OData $skip)",
            "schema": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
            },
        },
        "FilterParam": {
            "name": "$filter",
            "in": "query",
            "required": False,
            "description": "Строка фильтрации в стиле OData (e.g. Активен eq true)",
            "schema": {
                "type": "string",
            },
        },
    }


# ---------------------------------------------------------------------------
# Публичный класс
# ---------------------------------------------------------------------------

class OpenAPIGenerator:
    """Генератор OpenAPI 3.0.3 спецификации из JSON Schema словаря.

    Usage::

        from parser_1c.generator_schema.builder import SchemaBuilder
        from parser_1c.generator_openapi.generator import OpenAPIGenerator

        schemas  = SchemaBuilder(configuration).build()
        yaml_str = OpenAPIGenerator(configuration, schemas).generate()

    Args:
        configuration: Исходная конфигурация 1С.
        schemas:       Словарь JSON Schema от :class:`SchemaBuilder`.
        title:         Заголовок API (для ``info.title``).
        version:       Версия API (для ``info.version``).
        server_url:    Base URL сервера (добавляется в ``servers``).
        description:   Описание API (для ``info.description``).
    """

    def __init__(
        self,
        configuration: Configuration,
        schemas: dict[str, JsonSchema],
        *,
        title: str = "1C Configuration API",
        version: str = "1.0.0",
        server_url: str = "http://localhost:8000/api/v1",
        description: str = "Автоматически сгенерировано 1C2API",
    ) -> None:
        self.configuration = configuration
        self.schemas = schemas
        self.title = title
        self.version = version
        self.server_url = server_url
        self.description = description

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def generate(self) -> str:
        """Сгенерировать OpenAPI 3.0.3 спецификацию в формате YAML.

        Returns:
            Строка с валидным YAML документом OpenAPI 3.0.3.
        """
        spec = self._build_spec()
        return yaml.dump(
            spec,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
        )

    def generate_dict(self) -> dict[str, Any]:
        """Вернуть OpenAPI спецификацию как Python словарь (без сериализации).

        Удобно для тестирования и последующей обработки.
        """
        return self._build_spec()

    # ------------------------------------------------------------------
    # Сборка спецификации
    # ------------------------------------------------------------------

    def _build_spec(self) -> dict[str, Any]:
        """Собрать полный OpenAPI 3.0.3 документ."""
        # Стрипаем $schema и транслитерируем ключи — OAS 3.0 требует [a-zA-Z0-9._-]
        openapi_schemas = _transliterate_schema_keys(_strip_draft_uri(self.schemas))

        paths = self._build_paths()
        tags = self._build_tags()

        spec: dict[str, Any] = {
            "openapi": OAS_VERSION,
            "info": {
                "title": self.title,
                "version": self.version,
                "description": self.description,
                "contact": {
                    "name": "1C2API",
                    "url": "https://github.com/your-org/1c2api",
                },
            },
            "servers": [
                {
                    "url": self.server_url,
                    "description": "Основной сервер",
                }
            ],
            "tags": tags,
            "paths": paths,
            "components": {
                "schemas": openapi_schemas,
                "parameters": _build_shared_parameters(),
            },
        }

        logger.info(
            "OpenAPIGenerator: generated spec with %d paths, %d schemas",
            len(paths),
            len(openapi_schemas),
        )
        return spec

    def _build_paths(self) -> dict[str, Any]:
        """Построить блок paths со всеми CRUD эндпоинтами."""
        paths: dict[str, Any] = {}

        for catalog in self.configuration.catalogs:
            url_name   = catalog.name            # кириллица — используется в URL
            comp_name  = _to_component_name(catalog.name)  # ASCII — для $ref и operationId
            synonym    = catalog.synonym or catalog.name

            # /catalogs/{url_name}
            collection_path = f"/catalogs/{url_name}"
            paths[collection_path] = {
                "get":  _build_list_operation(comp_name, synonym),
                "post": _build_create_operation(comp_name, synonym),
            }

            # /catalogs/{url_name}/{id}
            item_path = f"/catalogs/{url_name}/{{id}}"
            paths[item_path] = {
                "parameters": [_ID_PARAM_REF],
                "get":    _build_get_by_id_operation(comp_name, synonym),
                "patch":  _build_patch_operation(comp_name, synonym),
                "delete": _build_delete_operation(comp_name, synonym),
            }

        return paths

    def _build_tags(self) -> list[dict[str, str]]:
        """Сформировать список тегов для документации."""
        tags: list[dict[str, str]] = [
            {
                "name": "Catalogs",
                "description": "CRUD операции над справочниками 1С",
            }
        ]
        if self.configuration.documents:
            tags.append(
                {
                    "name": "Documents",
                    "description": "CRUD операции над документами 1С",
                }
            )
        return tags


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _transliterate_schema_keys(schemas: dict[str, JsonSchema]) -> dict[str, JsonSchema]:
    """Переименовать ключи схем из кириллицы в ASCII для совместимости с OAS 3.0.

    OpenAPI 3.0 требует, чтобы ключи ``components/schemas`` содержали только
    ``[a-zA-Z0-9._-]``. Транслитерирует все ключи через :func:`_to_component_name`.

    Args:
        schemas: Словарь с произвольными ключами.

    Returns:
        Новый словарь с транслитерированными ключами.
    """
    return {_to_component_name(k): v for k, v in schemas.items()}


def _strip_draft_uri(schemas: dict[str, JsonSchema]) -> dict[str, JsonSchema]:
    """Удалить ``$schema`` из схем — OpenAPI 3.0 не поддерживает его в components.

    Args:
        schemas: Словарь JSON Schema (может содержать ``$schema`` на верхнем уровне).

    Returns:
        Новый словарь с теми же схемами, но без ``$schema`` в каждой.
    """
    cleaned: dict[str, JsonSchema] = {}
    for key, schema in schemas.items():
        cleaned[key] = {k: v for k, v in schema.items() if k != "$schema"}
    return cleaned
