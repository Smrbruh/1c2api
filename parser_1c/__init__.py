"""
parser-1c — Parse 1C:Enterprise EDT configurations and generate OpenAPI specs.
"""

from parser_1c.models import (
    Catalog,
    Configuration,
    Document,
    Enum1C,
    EnumValue,
    Field,
    OneCType,
    TabularSection,
)

__all__ = [
    "Catalog",
    "Configuration",
    "Document",
    "Enum1C",
    "EnumValue",
    "Field",
    "OneCType",
    "TabularSection",
]
