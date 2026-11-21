"""Decode a single raster in the project's offline Chromium sandbox and export sRGB PNG."""
import base64
import binascii

from fastapi import HTTPException


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
    except ImportError as exc:
        raise HTTPException(503, "Przetwarzanie obrazu wymaga Chromium.") from exc
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
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
            raise HTTPException(422, "Nie można odczytać obrazu. Limit wynosi 20 megapikseli.") from exc
        finally:
            await browser.close()
