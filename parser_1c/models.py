"""
Domain models for 1C:Enterprise configuration metadata.

These Pydantic v2 models represent the structural elements extracted from
1C EDT XML exports: fields, tabular sections, catalogs, documents, enums,
and the top-level Configuration aggregate.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field as PydanticField, model_validator


# ---------------------------------------------------------------------------
# Primitive value types understood by the OpenAPI generator
# ---------------------------------------------------------------------------

class OneCType(str, Enum):
    """Canonical set of 1C primitive types mapped to OpenAPI equivalents."""

    STRING = "String"
    NUMBER = "Number"
    BOOLEAN = "Boolean"
    DATE = "Date"
    REF = "CatalogRef"           # reference to another object
    ENUM = "EnumRef"
    UNDEFINED = "Undefined"      # type not resolved at parse time


# ---------------------------------------------------------------------------
# Field / Attribute
# ---------------------------------------------------------------------------

class Field(BaseModel):
    """A single attribute (реквизит) of a 1C metadata object.

    Attributes:
        name:        Internal name used in code (e.g. "Артикул").
        alias:       Human-readable synonym from the configuration
                     (e.g. "Артикул товара").  Defaults to *name* when absent.
        type:        Resolved 1C primitive type.
        required:    Whether the attribute is mandatory (FillChecking ≠ DontCheck).
        description: Free-form comment taken from the object's comment field.
    """

    name: str = PydanticField(..., min_length=1, description="Internal 1C name")
    alias: str = PydanticField("", description="Synonym / human-readable label")
    type: OneCType = PydanticField(
        default=OneCType.UNDEFINED,
        description="Resolved 1C primitive type",
    )
    required: bool = PydanticField(
        default=False,
        description="True when FillChecking is set to FillIfNotFilled",
    )
    description: str = PydanticField(
        default="",
        description="Comment from the metadata object",
    )

    @model_validator(mode="after")
    def _default_alias(self) -> "Field":
        """Fall back to *name* when synonym is absent."""
        if not self.alias:
            self.alias = self.name
        return self


# ---------------------------------------------------------------------------
# Tabular Section
# ---------------------------------------------------------------------------

class TabularSection(BaseModel):
    """A tabular section (табличная часть) belonging to a 1C object.

    Attributes:
        name:   Internal name of the tabular section.
        fields: Ordered list of columns (attributes) in this section.
    """

    name: str = PydanticField(..., min_length=1)
    fields: list[Field] = PydanticField(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level metadata objects
# ---------------------------------------------------------------------------

class Catalog(BaseModel):
    """1C Catalog (Справочник) metadata.

    Attributes:
        name:             Internal name (e.g. "Номенклатура").
        synonym:          Human-readable synonym.
        fields:           Header-level attributes (реквизиты шапки).
        tabular_sections: List of tabular sections attached to this catalog.
    """

    name: str = PydanticField(..., min_length=1)
    synonym: str = PydanticField(default="")
    fields: list[Field] = PydanticField(default_factory=list)
    tabular_sections: list[TabularSection] = PydanticField(default_factory=list)

    @model_validator(mode="after")
    def _default_synonym(self) -> "Catalog":
        if not self.synonym:
            self.synonym = self.name
        return self


class Document(BaseModel):
    """1C Document (Документ) metadata.

    Attributes:
        name:             Internal name.
        synonym:          Human-readable synonym.
        fields:           Header-level attributes.
        tabular_sections: Tabular sections attached to this document.
    """

    name: str = PydanticField(..., min_length=1)
    synonym: str = PydanticField(default="")
    fields: list[Field] = PydanticField(default_factory=list)
    tabular_sections: list[TabularSection] = PydanticField(default_factory=list)

    @model_validator(mode="after")
    def _default_synonym(self) -> "Document":
        if not self.synonym:
            self.synonym = self.name
        return self


class EnumValue(BaseModel):
    """A single value in a 1C Enum."""

    name: str = PydanticField(..., min_length=1)
    synonym: str = PydanticField(default="")

    @model_validator(mode="after")
    def _default_synonym(self) -> "EnumValue":
        if not self.synonym:
            self.synonym = self.name
        return self


class Enum1C(BaseModel):
    """1C Enumeration (Перечисление) metadata.

    Attributes:
        name:   Internal name.
        synonym: Human-readable synonym.
        values: Ordered list of enum members.
    """

    name: str = PydanticField(..., min_length=1)
    synonym: str = PydanticField(default="")
    values: list[EnumValue] = PydanticField(default_factory=list)

    @model_validator(mode="after")
    def _default_synonym(self) -> "Enum1C":
        if not self.synonym:
            self.synonym = self.name
        return self


# ---------------------------------------------------------------------------
# Configuration — root aggregate
# ---------------------------------------------------------------------------

class Configuration(BaseModel):
    """Root aggregate produced by any BaseParser implementation.

    Holds all parsed metadata objects grouped by their 1C type.

    Attributes:
        catalogs:  All parsed Catalog objects.
        documents: All parsed Document objects.
        enums:     All parsed Enum1C objects.
    """

    catalogs: list[Catalog] = PydanticField(default_factory=list)
    documents: list[Document] = PydanticField(default_factory=list)
    enums: list[Enum1C] = PydanticField(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience lookup helpers
    # ------------------------------------------------------------------

    def get_catalog(self, name: str) -> Optional[Catalog]:
        """Return the first catalog matching *name*, or ``None``."""
        return next((c for c in self.catalogs if c.name == name), None)

    def get_document(self, name: str) -> Optional[Document]:
        """Return the first document matching *name*, or ``None``."""
        return next((d for d in self.documents if d.name == name), None)

    def get_enum(self, name: str) -> Optional[Enum1C]:
        """Return the first enum matching *name*, or ``None``."""
        return next((e for e in self.enums if e.name == name), None)
