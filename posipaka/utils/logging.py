"""Налаштування логування (audit 102.12: structured JSON logging)."""

from __future__ import annotations

import sys

from loguru import logger


def setup_logging(
    json_mode: bool = False,
    log_level: str = "INFO",
    log_dir: str = "logs",
) -> None:
    """Налаштувати loguru.

    Development: rich human-readable format.
    Production/Docker: JSON structured для log aggregation.
    """
    logger.remove()

    if json_mode:
        # Production: JSON structured logging
        logger.add(
            sys.stderr,
            format="{message}",
            serialize=True,
            level=log_level,
        )
        logger.add(
            f"{log_dir}/posipaka.jsonl",
            serialize=True,
            rotation="50 MB",
            retention="30 days",
            compression="gz",
            level=log_level,
        )
    else:
        # Development: human-readable
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            level=log_level,
            colorize=True,
        )
        logger.add(
            f"{log_dir}/posipaka.log",
            rotation="10 MB",
            retention="7 days",
            level=log_level,
        )
