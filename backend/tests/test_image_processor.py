"""Screenshot normalization without Chromium (Pillow fallback)."""

from __future__ import annotations

import asyncio
import base64
import builtins
import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app import image_processor


def _encode(img: Image.Image, fmt: str) -> str:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def no_playwright(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_pillow_fallback_scales_and_flattens(no_playwright, fmt):
    mode = "RGB" if fmt == "JPEG" else "RGBA"
    src = Image.new(mode, (3200, 800), (255, 0, 0, 0) if mode == "RGBA" else (255, 0, 0))
    out = asyncio.run(image_processor.normalize_screenshot(_encode(src, fmt)))
    img = Image.open(io.BytesIO(base64.b64decode(out)))
    assert img.format == "PNG" and img.mode == "RGB"
    assert img.size == (1600, 400)
    if mode == "RGBA":
        assert img.getpixel((0, 0)) == (255, 255, 255)  # transparent pixels end up on white


def test_pillow_fallback_rejects_corrupt_image(no_playwright):
    corrupt = base64.b64encode(bytes.fromhex("89504e470d0a1a0a") + b"garbage").decode()
    with pytest.raises(HTTPException) as err:
        asyncio.run(image_processor.normalize_screenshot(corrupt))
    assert err.value.status_code == 422
