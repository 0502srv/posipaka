"""Vision Handler — обробка зображень через Claude Vision (секція 38.4 MASTER.md)."""

from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

SUPPORTED_FORMATS = {".jpeg", ".jpg", ".png", ".gif", ".webp"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


def encode_image_for_llm(image_path: Path) -> dict | None:
    """
    Підготувати зображення для Claude Vision API.

    Returns: dict для messages content block або None.
    """
    if not image_path.exists():
        return None

    suffix = image_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        logger.warning(f"Unsupported image format: {suffix}")
        return None

    size = image_path.stat().st_size
    if size > MAX_IMAGE_SIZE:
        logger.warning(f"Image too large: {size} bytes (max {MAX_IMAGE_SIZE})")
        return None

    media_type_map = {
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    data = image_path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("utf-8")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type_map[suffix],
            "data": b64,
        },
    }


def build_vision_message(image_path: Path, question: str = "") -> list[dict]:
    """
    Побудувати message content для Claude з зображенням.

    Можливості: аналіз фото, OCR, графіки, скріншоти, фото їжі → КБЖУ.
    """
    content: list[dict] = []

    image_block = encode_image_for_llm(image_path)
    if image_block:
        content.append(image_block)

    text = question or "Що зображено на цьому фото? Опиши детально."
    content.append({"type": "text", "text": text})

    return content
