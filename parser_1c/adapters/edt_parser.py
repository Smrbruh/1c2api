"""
EDT (Enterprise Development Tools) XML parser for 1C configurations.

Reads the standard EDT export directory layout produced by 1C:Enterprise
Development Tools (EDT) or ``ring`` CLI and converts it into the
:class:`~parser_1c.models.Configuration` domain model.

EDT export directory structure (relevant parts)::

    <root>/
    ├── Configuration.mdo
    └── Catalogs/
        ├── Номенклатура/
        │   ├── Номенклатура.mdo        ← main catalog XML
        │   └── TabularSections/
        │       └── ...
        └── ...

Namespace used across all EDT XML files:
    ``{http://v8.1c.ru/8.2/mdclasses}``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from lxml import etree

from parser_1c.adapters.base import BaseParser, ParseError
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Primary XML namespace used in all EDT MDO files.
NS = "http://v8.1c.ru/8.2/mdclasses"

#: Convenience shortcut for lxml Clark-notation namespace prefix.
_NS = f"{{{NS}}}"

#: Mapping from 1C type strings to :class:`~parser_1c.models.OneCType`.
_TYPE_MAP: dict[str, OneCType] = {
    "String":       OneCType.STRING,
    "Number":       OneCType.NUMBER,
    "Boolean":      OneCType.BOOLEAN,
    "Date":         OneCType.DATE,
    "Undefined":    OneCType.UNDEFINED,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tag(local: str) -> str:
    """Return Clark-notation tag name for *local* in the EDT namespace."""
    return f"{_NS}{local}"


def _text(element: etree._Element, xpath: str, default: str = "") -> str:
    """Extract text from the first match of *xpath* relative to *element*.

    Args:
        element: Context element for the XPath expression.
        xpath:   XPath string using the ``md:`` prefix bound to the EDT NS.
        default: Value returned when no match is found.

    Returns:
        Stripped text content of the first matching element, or *default*.
    """
    ns = {"md": NS}
    nodes = element.xpath(xpath, namespaces=ns)
    if nodes and nodes[0].text:
        return nodes[0].text.strip()
    return default


def _resolve_type(type_element: Optional[etree._Element]) -> OneCType:
    """Map a ``<Type>`` element's content to a :class:`~parser_1c.models.OneCType`.

    EDT stores types as qualified names like ``"String"`` or
    ``"CatalogRef.Номенклатура"``.  We resolve the base part only.

    Args:
        type_element: The ``<Type>`` element, or ``None``.

    Returns:
        The best-matching :class:`~parser_1c.models.OneCType`.
    """
    if type_element is None or not type_element.text:
        return OneCType.UNDEFINED

    raw = type_element.text.strip()
    base = raw.split(".")[0]  # "CatalogRef.Номенклатура" → "CatalogRef"

    if base in _TYPE_MAP:
        return _TYPE_MAP[base]
    if "CatalogRef" in base:
        return OneCType.REF
    if "EnumRef" in base:
        return OneCType.ENUM
    return OneCType.UNDEFINED


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------

class EDTParser(BaseParser):
    """Parse a 1C configuration exported in EDT (MDO) XML format.

    The parser traverses the ``Catalogs/``, ``Documents/``, and
    ``Enums/`` sub-directories under :attr:`~BaseParser.source_path`,
    reads each ``*.mdo`` file and constructs the corresponding domain objects.

    Usage::

        from pathlib import Path
        from parser_1c.adapters.edt_parser import EDTParser

        cfg = EDTParser(Path("/path/to/edt-export")).parse()
        print(cfg.get_catalog("Номенклатура"))

    Raises:
        FileNotFoundError: Propagated from :class:`~parser_1c.adapters.base.BaseParser`.
        ParseError: When an MDO file is structurally invalid.
    """

    def parse(self) -> Configuration:
        """Parse the entire EDT export directory.

        Returns:
            A :class:`~parser_1c.models.Configuration` containing all
            discovered catalogs, documents, and enumerations.
        """
        logger.info("Starting EDT parse: %s", self.source_path)

        catalogs = self._parse_catalogs()
        documents = self._parse_documents()
        enums = self._parse_enums()

        cfg = Configuration(catalogs=catalogs, documents=documents, enums=enums)
        logger.info(
            "EDT parse complete — catalogs=%d, documents=%d, enums=%d",
            len(catalogs), len(documents), len(enums),
        )
        return cfg

    # ------------------------------------------------------------------
    # Top-level object parsers
    # ------------------------------------------------------------------

    def _parse_catalogs(self) -> list[Catalog]:
        catalogs_dir = self.source_path / "Catalogs"
        if not catalogs_dir.is_dir():
            logger.debug("No Catalogs/ directory found — skipping")
            return []

        result: list[Catalog] = []
        for mdo_path in sorted(catalogs_dir.glob("**/*.mdo")):
            try:
                catalog = self._parse_catalog_file(mdo_path)
                if catalog is not None:
                    result.append(catalog)
            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError(
                    f"Unexpected error parsing catalog file: {exc}", mdo_path
                ) from exc

        logger.debug("Parsed %d catalogs", len(result))
        return result

    def _parse_documents(self) -> list[Document]:
        docs_dir = self.source_path / "Documents"
        if not docs_dir.is_dir():
            logger.debug("No Documents/ directory found — skipping")
            return []

        result: list[Document] = []
        for mdo_path in sorted(docs_dir.glob("**/*.mdo")):
            try:
                doc = self._parse_document_file(mdo_path)
                if doc is not None:
                    result.append(doc)
            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError(
                    f"Unexpected error parsing document file: {exc}", mdo_path
                ) from exc

        logger.debug("Parsed %d documents", len(result))
        return result

    def _parse_enums(self) -> list[Enum1C]:
        enums_dir = self.source_path / "Enums"
        if not enums_dir.is_dir():
            logger.debug("No Enums/ directory found — skipping")
            return []

        result: list[Enum1C] = []
        for mdo_path in sorted(enums_dir.glob("**/*.mdo")):
            try:
                enum = self._parse_enum_file(mdo_path)
                if enum is not None:
                    result.append(enum)
            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError(
                    f"Unexpected error parsing enum file: {exc}", mdo_path
                ) from exc

        logger.debug("Parsed %d enums", len(result))
        return result

    # ------------------------------------------------------------------
    # File-level parsers
    # ------------------------------------------------------------------

    def _parse_catalog_file(self, path: Path) -> Optional[Catalog]:
        """Parse a single catalog ``.mdo`` file.

        Args:
            path: Absolute path to the ``.mdo`` file.

        Returns:
            A :class:`~parser_1c.models.Catalog` instance, or ``None`` if the
            file does not contain a ``<Catalog>`` root element.

        Raises:
            ParseError: On XML parse errors or missing mandatory fields.
        """
        root = self._load_xml(path)
        catalog_el = root if root.tag == _tag("Catalog") else root.find(_tag("Catalog"))
        if catalog_el is None:
            logger.debug("No <Catalog> element in %s — skipping", path)
            return None

        name = _text(catalog_el, "md:Name")
        if not name:
            raise ParseError("Catalog has no <Name> element", path)

        synonym = self._extract_synonym(catalog_el)
        fields = self._extract_attributes(catalog_el)
        tabular_sections = self._extract_tabular_sections(catalog_el)

        return Catalog(
            name=name,
            synonym=synonym,
            fields=fields,
            tabular_sections=tabular_sections,
        )

    def _parse_document_file(self, path: Path) -> Optional[Document]:
        """Parse a single document ``.mdo`` file."""
        root = self._load_xml(path)
        doc_el = root if root.tag == _tag("Document") else root.find(_tag("Document"))
        if doc_el is None:
            logger.debug("No <Document> element in %s — skipping", path)
            return None

        name = _text(doc_el, "md:Name")
        if not name:
            raise ParseError("Document has no <Name> element", path)

        synonym = self._extract_synonym(doc_el)
        fields = self._extract_attributes(doc_el)
        tabular_sections = self._extract_tabular_sections(doc_el)

        return Document(
            name=name,
            synonym=synonym,
            fields=fields,
            tabular_sections=tabular_sections,
        )

    def _parse_enum_file(self, path: Path) -> Optional[Enum1C]:
        """Parse a single enum ``.mdo`` file."""
        root = self._load_xml(path)
        enum_el = root if root.tag == _tag("Enum") else root.find(_tag("Enum"))
        if enum_el is None:
            logger.debug("No <Enum> element in %s — skipping", path)
            return None

        name = _text(enum_el, "md:Name")
        if not name:
            raise ParseError("Enum has no <Name> element", path)

        synonym = self._extract_synonym(enum_el)
        values = self._extract_enum_values(enum_el)

        return Enum1C(name=name, synonym=synonym, values=values)

    # ------------------------------------------------------------------
    # Shared sub-element extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_synonym(element: etree._Element) -> str:
        """Extract the first ``<ru>`` text under ``<Synonym>``, if present."""
        ns = {"md": NS}
        nodes = element.xpath("md:Synonym/md:ru", namespaces=ns)
        if nodes and nodes[0].text:
            return nodes[0].text.strip()
        # Fallback: plain <Synonym> text (some EDTs omit language sub-tags)
        nodes = element.xpath("md:Synonym", namespaces=ns)
        if nodes and nodes[0].text:
            return nodes[0].text.strip()
        return ""

    def _extract_attributes(self, parent: etree._Element) -> list[Field]:
        """Extract all ``<Attributes>`` children of *parent* as :class:`Field` objects."""
        fields: list[Field] = []
        ns = {"md": NS}
        for attr_el in parent.xpath("md:Attributes", namespaces=ns):
            field = self._parse_attribute(attr_el)
            if field is not None:
                fields.append(field)
        return fields

    def _parse_attribute(self, attr_el: etree._Element) -> Optional[Field]:
        """Convert a single ``<Attributes>`` element to a :class:`Field`."""
        name = _text(attr_el, "md:Name")
        if not name:
            return None

        synonym = self._extract_synonym(attr_el)
        description = _text(attr_el, "md:Comment")

        # Resolve type: look for <Type> inside <AttributeType> or directly
        ns = {"md": NS}
        type_nodes = (
            attr_el.xpath("md:AttributeType/md:Type", namespaces=ns)
            or attr_el.xpath("md:Type/md:Types/md:Type", namespaces=ns)
            or attr_el.xpath("md:Type", namespaces=ns)
        )
        resolved_type = _resolve_type(type_nodes[0] if type_nodes else None)

        # Determine if the attribute is required (FillChecking ≠ DontCheck)
        fill_check = _text(attr_el, "md:FillChecking", "DontCheck")
        required = fill_check not in ("DontCheck", "")

        return Field(
            name=name,
            alias=synonym,
            type=resolved_type,
            required=required,
            description=description,
        )

    def _extract_tabular_sections(self, parent: etree._Element) -> list[TabularSection]:
        """Extract all ``<TabularSections>`` from *parent*."""
        sections: list[TabularSection] = []
        ns = {"md": NS}
        for ts_el in parent.xpath("md:TabularSections", namespaces=ns):
            ts = self._parse_tabular_section(ts_el)
            if ts is not None:
                sections.append(ts)
        return sections

    def _parse_tabular_section(self, ts_el: etree._Element) -> Optional[TabularSection]:
        """Convert a ``<TabularSections>`` element to a :class:`TabularSection`."""
        name = _text(ts_el, "md:Name")
        if not name:
            return None
        fields = self._extract_attributes(ts_el)
        return TabularSection(name=name, fields=fields)

    def _extract_enum_values(self, enum_el: etree._Element) -> list[EnumValue]:
        """Extract ``<EnumValues>`` children from an Enum element."""
        values: list[EnumValue] = []
        ns = {"md": NS}
        for val_el in enum_el.xpath("md:EnumValues", namespaces=ns):
            name = _text(val_el, "md:Name")
            if not name:
                continue
            synonym = self._extract_synonym(val_el)
            values.append(EnumValue(name=name, synonym=synonym))
        return values

    # ------------------------------------------------------------------
    # Low-level XML loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_xml(path: Path) -> etree._Element:
        """Parse an XML file and return its root element.

        Args:
            path: Path to the XML file.

        Returns:
            Root :class:`lxml.etree._Element`.

        Raises:
            ParseError: On XML syntax errors.
        """
        try:
            tree = etree.parse(str(path))  # noqa: S320 — local files only
            return tree.getroot()
        except etree.XMLSyntaxError as exc:
            raise ParseError(f"XML syntax error: {exc}", path) from exc
