"""Decode a single raster and export sRGB PNG (offline Chromium sandbox, Pillow fallback)."""
import asyncio
import base64
import binascii
import io
import logging

from fastapi import HTTPException

logger = logging.getLogger("ryziqo.image")

MAX_PIXELS = 20_000_000
MAX_SIDE = 1600
_UNREADABLE = "Nie można odczytać obrazu. Limit wynosi 20 megapikseli."


def _normalize_with_pillow(data: bytes) -> str:
    from PIL import Image, ImageCms, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if not w or not h or w * h > MAX_PIXELS:
                raise ValueError("dimensions")
            img = ImageOps.exif_transpose(img)
            icc = img.info.get("icc_profile")
            if icc:
                try:
                    src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    img = ImageCms.profileToProfile(img, src, ImageCms.createProfile("sRGB"),
                                                    outputMode="RGBA" if "A" in img.getbands() else "RGB")
                except Exception:  # broken / unsupported profile: keep the raw pixels
                    pass
            img = img.convert("RGBA")
            scale = min(1, MAX_SIDE / max(img.size))
            if scale < 1:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                                 Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", img.size, "white")
            canvas.paste(img, mask=img.getchannel("A"))
            out = io.BytesIO()
            canvas.save(out, "PNG")
    except Exception as exc:
        raise HTTPException(422, _UNREADABLE) from exc
    return base64.b64encode(out.getvalue()).decode("ascii")


async def normalize_screenshot(encoded: str) -> str:
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "Nieprawidłowy zapis obrazu.") from exc
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Limit obrazu wynosi 10 MB.")
    if data.startswith(bytes.fromhex("89504e470d0a1a0a")):
        mime = "image/png"
    elif data.startswith(bytes.fromhex("ffd8ff")):
        mime = "image/jpeg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise HTTPException(422, "Wybierz PNG, JPEG lub WebP.")
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return await asyncio.to_thread(_normalize_with_pillow, data)
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception as exc:  # package present but browser binaries missing
            logger.info("Chromium niedostępny, normalizacja obrazu przez Pillow: %s", exc)
            return await asyncio.to_thread(_normalize_with_pillow, data)
        try:
            page = await browser.new_page(offline=True)
            return await page.evaluate("""async ({mime, encoded}) => {
                const img = new Image();
                img.src = 'data:' + mime + ';base64,' + encoded;
                await new Promise((ok, fail) => { img.onload = ok; img.onerror = fail; });
                const w = img.naturalWidth, h = img.naturalHeight;
                if (!w || !h || w*h > 20000000) throw Error('dimensions');
                const scale = Math.min(1, 1600 / Math.max(w, h));
                const canvas = document.createElement('canvas');
                canvas.width = Math.max(1, Math.round(w*scale));
                canvas.height = Math.max(1, Math.round(h*scale));
                const ctx = canvas.getContext('2d', {colorSpace:'srgb'});
                ctx.fillStyle = 'white';
                ctx.fillRect(0,0,canvas.width,canvas.height);
                ctx.imageSmoothingQuality = 'high';
                ctx.drawImage(img,0,0,canvas.width,canvas.height);
                return canvas.toDataURL('image/png').split(',')[1];
            }""", {"mime": mime, "encoded": encoded})
        except Exception as exc:
            raise HTTPException(422, _UNREADABLE) from exc
        finally:
            await browser.close()
