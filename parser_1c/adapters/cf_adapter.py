"""
CFAdapter — парсер конфигурационных файлов 1C в формате .cf.

Принцип работы (два шага):
  1. ``1cv8.exe DESIGNER /RestoreIB``      — разворачивает .cf во временную ИБ
  2. ``1cv8.exe DESIGNER /DumpConfigToFiles``— выгружает конфигурацию в EDT XML

После выгрузки управление передаётся :class:`EDTParser`, который возвращает
готовый :class:`~parser_1c.models.Configuration`.

Временная ИБ гарантированно удаляется через ``finally``, даже при исключениях.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Sequence

from parser_1c.adapters.base import BaseParser, ParseError
from parser_1c.adapters.edt_parser import EDTParser
from parser_1c.models import Configuration

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

#: Имя исполняемого файла 1C по умолчанию (может быть переопределено через env).
DEFAULT_1C_EXECUTABLE = "1cv8.exe"

#: Таймаут на каждый subprocess.run (секунды).
_SUBPROCESS_TIMEOUT = 300  # 5 минут — хватает даже для крупных конфигураций


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _run_1c(
    args: Sequence[str],
    *,
    timeout: int = _SUBPROCESS_TIMEOUT,
    label: str = "1cv8",
) -> subprocess.CompletedProcess[bytes]:
    """Запустить команду 1C Designer и выбросить исключение при ошибке.

    Args:
        args:    Полная командная строка, включая ``1cv8.exe``.
        timeout: Таймаут в секундах.
        label:   Человекочитаемое название шага для сообщений об ошибках.

    Returns:
        :class:`subprocess.CompletedProcess` с returncode и stderr/stdout.

    Raises:
        ParseError: Если процесс завершился с ненулевым кодом или по таймауту.
    """
    logger.debug("[%s] running: %s", label, " ".join(str(a) for a in args))
    try:
        result = subprocess.run(
            args,
            capture_output=True,   # stdout+stderr не загрязняют консоль
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ParseError(
            f"Не найден исполняемый файл 1C: {args[0]!r}. "
            "Убедитесь, что 1cv8.exe доступен в PATH или задан явно."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ParseError(
            f"[{label}] Таймаут {timeout}с превышен при выполнении: {' '.join(str(a) for a in args)}"
        ) from exc

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
        raise ParseError(
            f"[{label}] 1cv8.exe завершился с кодом {result.returncode}.\n"
            f"stderr: {stderr_text or '(пусто)'}\n"
            f"stdout: {stdout_text or '(пусто)'}"
        )

    logger.debug("[%s] completed successfully (rc=0)", label)
    return result


# ---------------------------------------------------------------------------
# CFAdapter
# ---------------------------------------------------------------------------

class CFAdapter(BaseParser):
    """Парсер .cf файлов 1C через Designer-режим 1cv8.exe.

    Жизненный цикл разбора:

    .. code-block:: text

        .cf file
            │
            ▼  [1cv8.exe /RestoreIB]
        temp_db/   ← временная файловая ИБ (удаляется в finally)
            │
            ▼  [1cv8.exe /DumpConfigToFiles]
        output_dir/   ← EDT XML выгрузка
            │
            ▼  [EDTParser]
        Configuration

    Args:
        source_path:    Путь к файлу конфигурации (.cf).
        output_dir:     Куда сохранить EDT выгрузку. Если ``None``,
                        создаётся временная директория рядом с .cf файлом.
        executable_1c:  Путь к 1cv8.exe. По умолчанию ищет в PATH.

    Raises:
        ValueError:       Если source_path не является .cf файлом.
        FileNotFoundError: Если source_path не существует.
        ParseError:       При ошибках на любом шаге выгрузки.

    Example::

        from pathlib import Path
        from parser_1c.adapters.cf_adapter import CFAdapter

        cfg = CFAdapter(Path("MyConfig.cf")).parse()
        print(cfg.get_catalog("Номенклатура"))
    """

    def __init__(
        self,
        source_path: Path,
        *,
        output_dir: Path | None = None,
        executable_1c: str = DEFAULT_1C_EXECUTABLE,
    ) -> None:
        super().__init__(source_path)

        if self.source_path.suffix.lower() != ".cf":
            raise ValueError(
                f"CFAdapter ожидает файл .cf, получен: {self.source_path.suffix!r}"
            )

        self._output_dir: Path | None = output_dir.resolve() if output_dir else None
        self._executable = executable_1c

    # ------------------------------------------------------------------
    # Публичный интерфейс
    # ------------------------------------------------------------------

    def parse(self) -> Configuration:
        """Распаковать .cf, выгрузить в EDT XML и вернуть Configuration.

        Returns:
            Полностью заполненный :class:`~parser_1c.models.Configuration`.

        Raises:
            ParseError: При сбое любого subprocess-шага.
        """
        cf_path = self.source_path
        logger.info("CFAdapter: начинаем разбор %s", cf_path)

        # Если output_dir задан явно — используем его, иначе создаём tmp
        if self._output_dir is not None:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            return self._run_pipeline(cf_path, output_dir=self._output_dir)

        # output_dir не задан → временная папка рядом с cf файлом (или /tmp)
        base = cf_path.parent
        with tempfile.TemporaryDirectory(
            prefix="1c2api_edt_", dir=base if base.exists() else None
        ) as tmp_edt:
            return self._run_pipeline(cf_path, output_dir=Path(tmp_edt))

    # ------------------------------------------------------------------
    # Внутренний pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(self, cf_path: Path, *, output_dir: Path) -> Configuration:
        """Выполнить двух-шаговый pipeline с гарантированной очисткой temp_db.

        Шаг 1: RestoreIB   → разворачивает .cf в файловую ИБ
        Шаг 2: DumpConfigToFiles → выгружает конфигурацию в EDT XML

        Args:
            cf_path:    Абсолютный путь к .cf файлу.
            output_dir: Папка для EDT XML выгрузки (существующая или будет создана).
        """
        # Уникальное имя temp_db — исключает коллизии при параллельных запусках
        temp_db = output_dir / f"_1c2api_tmpdb_{uuid.uuid4().hex[:8]}"
        temp_db.mkdir(parents=True, exist_ok=True)
        logger.debug("temp_db создан: %s", temp_db)

        try:
            self._step_restore_ib(cf_path=cf_path, temp_db=temp_db)
            self._step_dump_config(temp_db=temp_db, output_dir=output_dir)
        finally:
            # Гарантированная очистка — даже при KeyboardInterrupt
            if temp_db.exists():
                shutil.rmtree(temp_db, ignore_errors=True)
                logger.debug("temp_db удалён: %s", temp_db)

        logger.info("CFAdapter: EDT выгрузка готова в %s, запускаем EDTParser", output_dir)
        return EDTParser(output_dir).parse()

    def _step_restore_ib(self, *, cf_path: Path, temp_db: Path) -> None:
        """Шаг 1: развернуть .cf в файловую ИБ через /RestoreIB.

        Эквивалент команды:
            1cv8.exe DESIGNER /FС:\\temp_db /RestoreIB C:\\config.cf

        Args:
            cf_path:  Путь к .cf файлу.
            temp_db:  Папка временной файловой ИБ.
        """
        _run_1c(
            [
                self._executable,
                "DESIGNER",
                f"/F{temp_db}",        # ключ без пробела — требование 1C API
                "/RestoreIB",
                str(cf_path),
            ],
            label="RestoreIB",
        )
        logger.info("Шаг 1/2 — RestoreIB завершён")

    def _step_dump_config(self, *, temp_db: Path, output_dir: Path) -> None:
        """Шаг 2: выгрузить конфигурацию в EDT XML через /DumpConfigToFiles.

        Эквивалент команды:
            1cv8.exe DESIGNER /FС:\\temp_db /DumpConfigToFiles С:\\output_dir

        Args:
            temp_db:    Папка временной файловой ИБ.
            output_dir: Папка назначения для EDT XML файлов.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        _run_1c(
            [
                self._executable,
                "DESIGNER",
                f"/F{temp_db}",
                "/DumpConfigToFiles",
                str(output_dir),
            ],
            label="DumpConfigToFiles",
        )
        logger.info("Шаг 2/2 — DumpConfigToFiles завершён → %s", output_dir)
