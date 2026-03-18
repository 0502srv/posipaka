"""Structured JSON Logging."""

from __future__ import annotations

import sys

from loguru import logger


def setup_logging(
    json_mode: bool = False,
    log_level: str = "INFO",
    log_dir: str = "logs",
) -> None:
    """
    Development: rich human-readable.
    Production: JSON structured для log aggregation.
    """
    logger.remove()

    if json_mode:
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
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level:<7}</level> | "
                "<cyan>{name}</cyan> — <level>{message}</level>"
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
