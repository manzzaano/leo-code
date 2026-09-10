"""Smoke test: setup_logging crea el log file, es idempotente (no duplica
handlers en llamadas repetidas) y respeta el nivel pedido."""

import logging

from leo_code.logging_config import setup_logging


def _clean_logger():
    logger = logging.getLogger("leo")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()


def test_setup_logging_creates_log_file(tmp_path):
    _clean_logger()
    log_file = setup_logging(repo=str(tmp_path))

    assert log_file == tmp_path / ".leo-code" / "logs" / "leo-code.log"
    assert log_file.parent.is_dir()


def test_setup_logging_is_idempotent(tmp_path):
    _clean_logger()
    setup_logging(repo=str(tmp_path))
    setup_logging(repo=str(tmp_path))

    logger = logging.getLogger("leo")
    assert len(logger.handlers) == 1


def test_setup_logging_respects_level(tmp_path):
    _clean_logger()
    setup_logging(repo=str(tmp_path), level="DEBUG")

    logger = logging.getLogger("leo")
    assert logger.level == logging.DEBUG
