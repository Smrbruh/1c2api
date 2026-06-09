"""Adapters for different 1C export formats."""

from parser_1c.adapters.base import BaseParser, ParseError
from parser_1c.adapters.edt_parser import EDTParser

__all__ = ["BaseParser", "ParseError", "EDTParser"]
