"""Configuración mínima de logging a fichero, compartida por CLI y MCP server."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 2


def setup_logging(repo: str | None = None, level: str | None = None) -> Path:
    """Configura el logger raiz "leo" con un RotatingFileHandler. Idempotente.

    Args:
        repo: raíz del repo bajo la que vive .leo-code/logs/. Si None, usa cwd.
        level: nivel de logging (DEBUG, INFO, WARNING, ERROR). Default desde LEO_LOG_LEVEL env var o INFO.

    Returns:
        Path del fichero de log.
    """
    logger = logging.getLogger("leo")

    repo_path = Path(repo).resolve() if repo else Path.cwd()
    log_dir = repo_path / ".leo-code" / "logs"
    log_file = log_dir / "leo-code.log"

    if any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_file)
           for h in logger.handlers):
        return log_file

    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logger.addHandler(handler)
    logger.setLevel(getattr(logging, (level or os.getenv("LEO_LOG_LEVEL", "INFO")).upper(), logging.INFO))
    logger.propagate = False

    return log_file
