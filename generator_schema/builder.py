"""
generator_schema/builder.py — JSON Schema Draft-07 builder.

Преобразует :class:`~parser_1c.models.Configuration` в словарь JSON Schema
(по одной схеме на каждый Catalog/Document).

Маппинг типов 1C → JSON Schema
--------------------------------
+---------------------+-------------------------------------------------+
| OneCType            | JSON Schema                                     |
+=====================+=================================================+
| String              | {"type": "string"}                              |
| Number              | {"type": "number"}                              |
| Boolean             | {"type": "boolean"}                             |
| Date                | {"type": "string", "format": "date-time"}       |
| CatalogRef.*        | {"type": "string", "format": "uuid",            |
|                     |  "description": "Ссылка на <Name>"}             |
| EnumRef.*           | {"type": "string",                              |
|                     |  "description": "Значение перечисления <Name>"} |
| Undefined           | {}  (permissive schema)                         |
+---------------------+-------------------------------------------------+

TabularSection маппится в массив объектов::

    {
      "type": "array",
      "title": "<SectionName>",
      "items": {
        "type": "object",
        "properties": { ... },
        "required": [...]
      }
    }

Выходной словарь имеет форму::

    {
        "Номенклатура": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Номенклатура",
            "description": "Справочник «Номенклатура»",
            "type": "object",
            "properties": { ... },
            "required": [...],
        },
        ...
    }
"""

from __future__ import annotations

import logging
from typing import Any

from parser_1c.models import Catalog, Configuration, Document, Field, OneCType, TabularSection

logger = logging.getLogger(__name__)

# Тип JSON Schema — любой dict[str, Any]
JsonSchema = dict[str, Any]

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_DRAFT07_URI = "http://json-schema.org/draft-07/schema#"

# Системные поля, добавляемые к каждому объекту (не из конфигурации 1С)
_SYSTEM_PROPERTIES: dict[str, JsonSchema] = {
    "_id": {
        "type": "string",
        "format": "uuid",
        "description": "Уникальный идентификатор объекта (GUID 1С)",
        "readOnly": True,
    },
    "DeletionMark": {
        "type": "boolean",
        "description": "Пометка удаления",
        "default": False,
    },
    "Code": {
        "type": "string",
        "description": "Код элемента справочника",
    },
    "Description": {
        "type": "string",
        "description": "Наименование элемента справочника",
    },
}

# Системные поля, которые всегда readOnly (не входят во *Input схему)
_READONLY_SYSTEM_FIELDS = frozenset({"_id"})


# ---------------------------------------------------------------------------
# Маппинг типов
# ---------------------------------------------------------------------------

def _map_field_type(field: Field) -> JsonSchema:
    """Преобразовать тип реквизита 1С в JSON Schema.

    Args:
        field: Реквизит с заполненным полем :attr:`~parser_1c.models.Field.type`.

    Returns:
        JSON Schema фрагмент для данного типа.
    """
    t = field.type

    if t == OneCType.STRING:
        return {"type": "string"}

    if t == OneCType.NUMBER:
        return {"type": "number"}

    if t == OneCType.BOOLEAN:
        return {"type": "boolean"}

    if t == OneCType.DATE:
        return {"type": "string", "format": "date-time"}

    if t == OneCType.REF:
        # CatalogRef.Номенклатура → имя берём из description или alias
        ref_target = field.description or field.alias or field.name
        return {
            "type": "string",
            "format": "uuid",
            "description": f"Ссылка на {ref_target}",
        }

    if t == OneCType.ENUM:
        enum_name = field.description or field.alias or field.name
        return {
            "type": "string",
            "description": f"Значение перечисления {enum_name}",
        }

    # OneCType.UNDEFINED — пермиссивная схема
    return {}


def _build_field_schema(field: Field) -> JsonSchema:
    """Собрать полную JSON Schema для одного реквизита, включая мета-поля."""
    schema = _map_field_type(field)

    if field.alias and field.alias != field.name:
        schema["title"] = field.alias

    if field.description:
        # description может уже быть проставлен _map_field_type для Ref/Enum;
        # переписываем только если ещё не задан там
        schema.setdefault("description", field.description)

    return schema


def _build_tabular_section_schema(ts: TabularSection) -> JsonSchema:
    """Построить JSON Schema для табличной части (тип array)."""
    props: dict[str, JsonSchema] = {}
    required: list[str] = []

    for field in ts.fields:
        props[field.name] = _build_field_schema(field)
        if field.required:
            required.append(field.name)

    items_schema: JsonSchema = {
        "type": "object",
        "properties": props,
    }
    if required:
        items_schema["required"] = required

    result: JsonSchema = {
        "type": "array",
        "title": ts.name,
        "items": items_schema,
    }
    return result


def _build_object_schema(
    *,
    name: str,
    synonym: str,
    fields: list[Field],
    tabular_sections: list[TabularSection],
    include_system_fields: bool = True,
    include_draft_uri: bool = True,
    is_input: bool = False,
) -> JsonSchema:
    """Общий строитель JSON Schema для Catalog или Document.

    Args:
        name:                  Внутреннее имя объекта (e.g. "Номенклатура").
        synonym:               Синоним / заголовок.
        fields:                Список реквизитов.
        tabular_sections:      Список табличных частей.
        include_system_fields: Добавить ли системные поля (_id, Code и т.д.).
        include_draft_uri:     Включить ли ``$schema`` URI.
        is_input:              True → генерировать *Input* схему (без readOnly полей).

    Returns:
        Словарь JSON Schema Draft-07.
    """
    properties: dict[str, JsonSchema] = {}
    required_fields: list[str] = []

    # 1. Системные поля (только для «полной» схемы, не для Input)
    if include_system_fields and not is_input:
        for sys_name, sys_schema in _SYSTEM_PROPERTIES.items():
            properties[sys_name] = sys_schema.copy()

    # 2. Реквизиты из конфигурации 1С
    for field in fields:
        if is_input and "readOnly" in _build_field_schema(field):
            continue  # пропускаем readOnly поля во входной схеме
        properties[field.name] = _build_field_schema(field)
        if field.required:
            required_fields.append(field.name)

    # 3. Табличные части
    for ts in tabular_sections:
        properties[ts.name] = _build_tabular_section_schema(ts)

    schema: JsonSchema = {
        "type": "object",
        "title": synonym or name,
        "description": f"Справочник «{synonym or name}»" if not is_input else f"Входные данные для {synonym or name}",
        "properties": properties,
        "additionalProperties": False,
    }

    if required_fields:
        schema["required"] = required_fields

    if include_draft_uri and not is_input:
        schema["$schema"] = _DRAFT07_URI

    return schema


# ---------------------------------------------------------------------------
# Публичный класс
# ---------------------------------------------------------------------------

class SchemaBuilder:
    """Строитель JSON Schema Draft-07 из :class:`~parser_1c.models.Configuration`.

    Для каждого :class:`~parser_1c.models.Catalog` генерирует две схемы:
    - ``{name}Item``  — полная схема объекта (с системными полями, readOnly).
    - ``{name}Input`` — схема для POST/PATCH запросов (без readOnly полей).

    Usage::

        builder = SchemaBuilder(configuration)
        schemas = builder.build()
        # schemas["НоменклатураItem"]  → полная JSON Schema
        # schemas["НоменклатураInput"] → входная JSON Schema

    Attributes:
        configuration: Исходный :class:`~parser_1c.models.Configuration`.
    """

    def __init__(self, configuration: Configuration) -> None:
        self.configuration = configuration

    def build(self) -> dict[str, JsonSchema]:
        """Построить JSON Schema для всех объектов конфигурации.

        Returns:
            Словарь ``{schema_name: json_schema_dict}``.
            Ключи: ``{CatalogName}Item``, ``{CatalogName}Input``,
                   ``{DocumentName}Item``, ``{DocumentName}Input``,
                   плюс общая схема ``Error``.
        """
        schemas: dict[str, JsonSchema] = {}

        # Общая схема ошибки
        schemas["Error"] = _build_error_schema()

        # Схемы для справочников
        for catalog in self.configuration.catalogs:
            logger.debug("Building schemas for catalog: %s", catalog.name)
            item_key  = f"{catalog.name}Item"
            input_key = f"{catalog.name}Input"

            schemas[item_key] = _build_object_schema(
                name=catalog.name,
                synonym=catalog.synonym,
                fields=catalog.fields,
                tabular_sections=catalog.tabular_sections,
                include_system_fields=True,
                include_draft_uri=True,
                is_input=False,
            )
            schemas[input_key] = _build_object_schema(
                name=catalog.name,
                synonym=catalog.synonym,
                fields=catalog.fields,
                tabular_sections=catalog.tabular_sections,
                include_system_fields=False,
                include_draft_uri=False,
                is_input=True,
            )

        # Схемы для документов
        for doc in self.configuration.documents:
            logger.debug("Building schemas for document: %s", doc.name)
            item_key  = f"{doc.name}Item"
            input_key = f"{doc.name}Input"

            schemas[item_key] = _build_object_schema(
                name=doc.name,
                synonym=doc.synonym,
                fields=doc.fields,
                tabular_sections=doc.tabular_sections,
                include_system_fields=True,
                include_draft_uri=True,
                is_input=False,
            )
            schemas[input_key] = _build_object_schema(
                name=doc.name,
                synonym=doc.synonym,
                fields=doc.fields,
                tabular_sections=doc.tabular_sections,
                include_system_fields=False,
                include_draft_uri=False,
                is_input=True,
            )

        logger.info(
            "SchemaBuilder: built %d schemas for %d catalogs / %d documents",
            len(schemas),
            len(self.configuration.catalogs),
            len(self.configuration.documents),
        )
        return schemas

    # ------------------------------------------------------------------
    # Одиночные хелперы (полезны в тестах и CLI)
    # ------------------------------------------------------------------

    def build_catalog(self, name: str) -> tuple[JsonSchema, JsonSchema]:
        """Вернуть (ItemSchema, InputSchema) для конкретного каталога по имени.

        Args:
            name: Внутреннее имя каталога.

        Returns:
            Кортеж ``(item_schema, input_schema)``.

        Raises:
            KeyError: Если каталог с таким именем не найден.
        """
        catalog = self.configuration.get_catalog(name)
        if catalog is None:
            available = [c.name for c in self.configuration.catalogs]
            raise KeyError(
                f"Каталог {name!r} не найден. Доступные: {available}"
            )
        item = _build_object_schema(
            name=catalog.name,
            synonym=catalog.synonym,
            fields=catalog.fields,
            tabular_sections=catalog.tabular_sections,
            include_system_fields=True,
            include_draft_uri=True,
            is_input=False,
        )
        inp = _build_object_schema(
            name=catalog.name,
            synonym=catalog.synonym,
            fields=catalog.fields,
            tabular_sections=catalog.tabular_sections,
            include_system_fields=False,
            include_draft_uri=False,
            is_input=True,
        )
        return item, inp


# ---------------------------------------------------------------------------
# Вспомогательные схемы
# ---------------------------------------------------------------------------

def _build_error_schema() -> JsonSchema:
    """Стандартная схема ошибки API."""
    return {
        "type": "object",
        "title": "Error",
        "description": "Стандартный ответ с ошибкой",
        "required": ["code", "message"],
        "properties": {
            "code": {
                "type": "integer",
                "description": "HTTP статус-код или код ошибки приложения",
            },
            "message": {
                "type": "string",
                "description": "Человекочитаемое описание ошибки",
            },
            "details": {
                "type": "array",
                "description": "Детализация ошибок валидации",
                "items": {
                    "type": "object",
                    "properties": {
                        "field":   {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
            },
        },
        "additionalProperties": False,
    }
