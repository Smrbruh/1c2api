"""
Abstract base class for 1C configuration parsers.

New parser implementations (EDT, cf-export, Designer XML, …) must subclass
``BaseParser`` and implement the ``parse()`` method.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from parser_1c.models import Configuration

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Abstract parser interface for 1C configuration sources.

    Subclasses are responsible for:
    - reading the source (file system, archive, API, …)
    - extracting metadata objects
    - returning a fully-populated :class:`~parser_1c.models.Configuration`

    Example::

        class MyParser(BaseParser):
            def parse(self) -> Configuration:
                ...

        cfg = MyParser(source_path=Path("/tmp/my-export")).parse()
    """

    def __init__(self, source_path: Path) -> None:
        """Initialise the parser with the root path of the source export.

        Args:
            source_path: Absolute or relative path to the export root directory
                         (or a single file, depending on the implementation).

        Raises:
            FileNotFoundError: If *source_path* does not exist.
        """
        resolved = source_path.resolve()
        if not resolved.exists():
            raise FileNotFoundError(
                f"Parser source path does not exist: {resolved}"
            )
        self.source_path: Path = resolved
        logger.debug("%s initialised with source_path=%s", type(self).__name__, resolved)

    @abstractmethod
    def parse(self) -> Configuration:
        """Parse the source and return a :class:`~parser_1c.models.Configuration`.

        Returns:
            A Configuration instance populated with all objects found in the
            source.

        Raises:
            ParseError: On unrecoverable structural errors in the source.
        """

    # ------------------------------------------------------------------
    # Utility helpers available to all subclasses
    # ------------------------------------------------------------------

    def _iter_xml_files(self, glob: str = "**/*.xml") -> list[Path]:
        """Yield XML file paths under :attr:`source_path` matching *glob*.

        Args:
            glob: Glob pattern relative to ``source_path``.

        Returns:
            Sorted list of matching :class:`~pathlib.Path` objects.
        """
        files = sorted(self.source_path.glob(glob))
        logger.debug("Found %d XML files matching '%s'", len(files), glob)
        return files


class ParseError(Exception):
    """Raised when a parser encounters an unrecoverable structural problem.

    Attributes:
        path:    Source file that triggered the error (when applicable).
        message: Human-readable description of the problem.
    """

    def __init__(self, message: str, path: Path | None = None) -> None:
        self.path = path
        self.message = message
        location = f" [{path}]" if path else ""
        super().__init__(f"ParseError{location}: {message}")
