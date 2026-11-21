"""Local OCR fallback for screenshots when no vision model (VLM) is available.

Uses RapidOCR (PP-OCRv4 ONNX models bundled in the wheel, CPU only, no network). It is optional:
installed in the Docker image unless built with --build-arg INSTALL_OCR=false. Without it,
`read_text` returns None and the API keeps answering 503 for screenshots when Ollama is down.
The bundled recognition model has a Chinese/English character set, so Polish diacritics may be
read as plain Latin letters; the result is labelled as an OCR reading in the report limitations.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("ryziqo.ocr")

MIN_CONFIDENCE = 0.5
_engine: Any = None
_unavailable = False
_lock = threading.Lock()


def _get_engine() -> Any:
    global _engine, _unavailable
    if _engine is not None or _unavailable:
        return _engine
    with _lock:
        if _engine is None and not _unavailable:
            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]

                _engine = RapidOCR()
            except Exception as exc:  # ImportError, missing system libraries, broken model files
                logger.info("Lokalny OCR niedostępny: %s", exc)
                _unavailable = True
    return _engine


def lines_from_result(result: Any) -> list[str]:
    """RapidOCR result ([[box, text, score], ...]) -> text lines in reading order."""
    items = []
    for entry in result or []:
        try:
            box, text, score = entry[0], str(entry[1]).strip(), float(entry[2])
            top = min(point[1] for point in box)
            left = min(point[0] for point in box)
        except (TypeError, ValueError, IndexError):
            continue
        if text and score >= MIN_CONFIDENCE:
            items.append((top, left, text))
    if not items:
        return []
    # Group boxes whose tops are close into one visual line, then order left to right
    items.sort()
    lines: list[list[tuple[float, float, str]]] = []
    for item in items:
        if lines and abs(item[0] - lines[-1][0][0]) <= 12:
            lines[-1].append(item)
        else:
            lines.append([item])
    return [" ".join(t for _, _, t in sorted(line, key=lambda i: i[1])) for line in lines]


def read_text(image: bytes) -> str | None:
    """Text read from an image, "" when nothing legible, None when OCR is not installed."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        result, _ = engine(image)
    except Exception as exc:
        logger.warning("Błąd lokalnego OCR: %s", exc)
        return ""
    return "\n".join(lines_from_result(result))
