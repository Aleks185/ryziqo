"""Headless Chromium renderer (Playwright) for JavaScript-rendered pages.

Used as an optional fallback by `PageFetcher`. It renders the page, measures risk-disclosure
presentation from *computed* styles (font size, WCAG contrast, footer/legal placement, content
behind a closed <details>, mobile overflow) and returns the rendered DOM.

Security model:
- every browser request (navigation, redirects, sub-resources) and every WebSocket is re-validated
  with the anti-SSRF guard; DNS lookups run in a thread so they never block the event loop,
- service workers and downloads are disabled, images/media/fonts are not fetched,
- the rendered HTML is capped at CRAWLER_MAX_BYTES and concurrency is limited.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from app.ai.preprocessor import RISK_KEYWORDS_RE, RISK_WARNING_CLAUSE_RE
from app.config import Settings
from app.scraper.ssrf import SSRFError, validate_public_url

logger = logging.getLogger("investwatch.browser")

BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
# With screenshots (VLM analysis) images must load, or banners would be blank; still SSRF-guarded
SCREENSHOT_BLOCKED_RESOURCE_TYPES = frozenset({"media"})
SCREENSHOT_JPEG_QUALITY = 70
CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",  # Docker's default /dev/shm (64 MB) crashes Chromium
    "--disable-gpu",
    "--no-first-run",
    "--disable-background-networking",
    "--disable-sync",
]
MAX_CONCURRENT_RENDERS = 2
# Rule 8 (UKNF criteria): risk information must stay readable on desktop, tablet and phone
VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1280, "height": 800},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 667},
}

# Runs in the page. Mirrors preprocessor.extract_dom_metrics, but on computed styles,
# so external stylesheets, CSS classes and JS-applied styles are taken into account.
COMPUTED_METRICS_JS = r"""
([riskPattern, warningPattern]) => {
  const riskRe = new RegExp(riskPattern, 'i');
  const warningRe = new RegExp(warningPattern, 'i');  // substantive clause, not just "CFD"
  const parseRGB = (s) => {
    const m = /rgba?\(([^)]+)\)/.exec(s || '');
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const channel = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const backgroundOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = parseRGB(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0.5) return c;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const effectiveOpacity = (el) => {
    let o = 1;
    for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity || '1');
    return o;
  };
  const BLOCK = 'p,li,div,span,small,footer,summary,td,section,article,label';
  const LEGAL = 'footer,[id*="legal" i],[class*="legal" i],[class*="footnote" i],[class*="disclaimer" i]';

  const normalFonts = [];  // [fontPx, textLength]
  const riskFonts = [];
  let minRiskContrast = null, inFooter = false, behindClick = false, lowContrast = false, riskNodes = 0;
  let shownOutsideFooter = false, shownOutsideDetails = false;  // warning also visible in the body
  const seenBlocks = new Set();

  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = (walker.currentNode.textContent || '').trim();
    if (text.length < 3) continue;
    const el = walker.currentNode.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    const fontPx = parseFloat(cs.fontSize) || 16;
    const block = el.closest(BLOCK) || el;
    const blockText = (block.textContent || '').slice(0, 1200);
    const isRisk = riskRe.test(text) || (blockText.length < 1200 && riskRe.test(blockText));
    const closedDetails = el.closest('details:not([open])');
    const rect = el.getBoundingClientRect();
    const rendered = cs.display !== 'none' && cs.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;

    if (!isRisk) {
      if (rendered && fontPx >= 12) normalFonts.push([fontPx, text.length]);
      continue;
    }
    riskNodes += 1;
    riskFonts.push(fontPx);
    const inLegal = !!el.closest(LEGAL);
    const hiddenByClick = !!closedDetails && !el.closest('summary');
    const shownWarning = rendered && warningRe.test(text);
    if (inLegal) inFooter = true; else if (shownWarning) shownOutsideFooter = true;
    if (hiddenByClick) behindClick = true; else if (shownWarning) shownOutsideDetails = true;
    if (seenBlocks.has(block)) continue;
    seenBlocks.add(block);
    const fg = parseRGB(cs.color);
    if (fg) {
      const ratio = contrast(fg, backgroundOf(el));
      minRiskContrast = minRiskContrast === null ? ratio : Math.min(minRiskContrast, ratio);
      if (ratio < 4.5) lowContrast = true;  // WCAG 2.x AA, normal text
    }
    if (effectiveOpacity(el) < 0.6) lowContrast = true;
  }

  // Length-weighted median font size of regular (non-risk) visible text
  let dominant = null;
  if (normalFonts.length) {
    normalFonts.sort((a, b) => a[0] - b[0]);
    const total = normalFonts.reduce((s, f) => s + f[1], 0);
    let acc = 0;
    for (const [px, len] of normalFonts) { acc += len; if (acc >= total / 2) { dominant = px; break; } }
  }
  return {
    dominant_font_px: dominant,
    risk_font_px: riskFonts.length ? Math.min(...riskFonts) : null,
    risk_min_contrast: minRiskContrast === null ? null : Math.round(minRiskContrast * 100) / 100,
    low_contrast_detected: lowContrast,
    risk_hidden_in_footer: inFooter && !shownOutsideFooter,
    requires_click_to_view_risk: behindClick && !shownOutsideDetails,
    risk_nodes: riskNodes,
  };
}
"""

MOBILE_OVERFLOW_JS = """
() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() =>
  resolve(document.documentElement.scrollWidth > window.innerWidth + 10))))
"""


@dataclass
class RenderResult:
    html: str
    final_url: str
    metrics: dict[str, Any] = field(default_factory=dict)
    blocked_requests: int = 0
    # JPEG viewport screenshots: [desktop 1280x800, mobile 375x667] when requested
    screenshots: list[bytes] = field(default_factory=list)


def playwright_proxy_config(proxy: str | None) -> dict[str, str] | None:
    """Translate a proxy URL (optionally with user:password@) to Playwright's proxy dict."""
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Nieprawidłowy adres proxy: {proxy!r}")
    server = f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
    config = {"server": server}
    if parsed.username:
        config["username"] = unquote(parsed.username)
        config["password"] = unquote(parsed.password or "")
    return config


def _as_http_url(url: str) -> str:
    """ws(s):// -> http(s):// so WebSocket targets go through the same anti-SSRF validation."""
    if url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://"):]
    return url


class BrowserRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

    @staticmethod
    def is_available() -> bool:
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            return False
        return True

    async def _is_allowed(self, url: str, host_cache: dict[str, bool]) -> bool:
        if url.startswith(("data:", "blob:", "about:")):
            return True
        url = _as_http_url(url)
        parsed = urlparse(url)
        # Cache per scheme + authority (incl. credentials/port), so one DNS check covers all assets of a host
        key = f"{parsed.scheme}://{parsed.netloc}".lower()
        if key not in host_cache:
            try:
                await asyncio.to_thread(validate_public_url, url)
                host_cache[key] = True
            except SSRFError:
                host_cache[key] = False
        return host_cache[key]

    async def render(
        self, url: str, user_agent: str, proxy: str | None = None, capture_screenshots: bool = False
    ) -> RenderResult:
        """Render `url` in headless Chromium. Raises on navigation/SSRF errors."""
        from playwright.async_api import async_playwright

        validate_public_url(url)
        timeout_ms = int(self.settings.crawler_playwright_timeout_seconds * 1000)
        host_cache: dict[str, bool] = {}
        blocked = 0
        blocked_types = SCREENSHOT_BLOCKED_RESOURCE_TYPES if capture_screenshots else BLOCKED_RESOURCE_TYPES
        screenshots: list[bytes] = []

        async with self._semaphore, async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, args=CHROMIUM_ARGS, proxy=playwright_proxy_config(proxy)  # type: ignore[arg-type]
            )
            try:
                context = await browser.new_context(
                    viewport=VIEWPORTS["desktop"],
                    user_agent=user_agent,
                    locale="pl-PL",
                    service_workers="block",
                    accept_downloads=False,
                    java_script_enabled=True,
                )
                context.set_default_timeout(timeout_ms)

                async def guard_request(route) -> None:  # type: ignore[no-untyped-def]
                    nonlocal blocked
                    request = route.request
                    if request.resource_type in blocked_types:
                        await route.abort()
                        return
                    if not await self._is_allowed(request.url, host_cache):
                        blocked += 1
                        logger.warning("Zablokowano żądanie przeglądarki (anty-SSRF): %s", request.url)
                        await route.abort("blockedbyclient")
                        return
                    # Chromium follows redirects internally without calling this handler again (both for
                    # route.continue_() and for a fulfilled 3xx), so the redirect chain is walked here,
                    # validating every hop, and only the final response is handed to the browser.
                    try:
                        hop_url = request.url
                        method = request.method
                        response = await route.fetch(max_redirects=0)
                        for _ in range(self.settings.crawler_max_redirects + 1):
                            location = response.headers.get("location")
                            if not (300 <= response.status < 400 and location):
                                break
                            hop_url = urljoin(hop_url, location)
                            if not await self._is_allowed(hop_url, host_cache):
                                blocked += 1
                                logger.warning("Zablokowano przekierowanie przeglądarki (anty-SSRF): %s", hop_url)
                                await route.abort("blockedbyclient")
                                return
                            if response.status in (301, 302, 303):
                                method = "GET"
                            response = await route.fetch(url=hop_url, method=method, max_redirects=0)
                        else:
                            await route.abort("failed")
                            return
                    except Exception as exc:
                        logger.info("Żądanie przeglądarki nieudane %s: %s", request.url, exc)
                        await route.abort("failed")
                        return
                    await route.fulfill(response=response)

                async def guard_websocket(ws) -> None:  # type: ignore[no-untyped-def]
                    nonlocal blocked
                    if await self._is_allowed(ws.url, host_cache):
                        ws.connect_to_server()
                    else:
                        blocked += 1
                        logger.warning("Zablokowano WebSocket przeglądarki (anty-SSRF): %s", ws.url)
                        await ws.close()

                await context.route("**/*", guard_request)
                await context.route_web_socket("**/*", guard_websocket)

                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:  # SPAs keep fetching data after DOMContentLoaded; wait briefly, never fail on it
                    await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 5000))
                except Exception:
                    pass

                final_url = page.url
                validate_public_url(final_url)
                html = await page.content()
                if len(html.encode("utf-8")) > self.settings.crawler_max_bytes:
                    raise ValueError(
                        f"Wyrenderowany DOM przekracza limit {self.settings.crawler_max_bytes} B."
                    )

                metrics: dict[str, Any] = {"computed": await page.evaluate(
                    COMPUTED_METRICS_JS, [RISK_KEYWORDS_RE.pattern, RISK_WARNING_CLAUSE_RE.pattern]
                )}
                if capture_screenshots:
                    screenshots.append(await page.screenshot(type="jpeg", quality=SCREENSHOT_JPEG_QUALITY))
                overflow: dict[str, bool] = {}
                for name in ("tablet", "mobile"):
                    await page.set_viewport_size(VIEWPORTS[name])
                    overflow[name] = bool(await page.evaluate(MOBILE_OVERFLOW_JS))
                    if capture_screenshots:
                        screenshots.append(await page.screenshot(type="jpeg", quality=SCREENSHOT_JPEG_QUALITY))
                metrics["responsive_overflow_by_viewport"] = overflow
                metrics["responsive_overflow_detected"] = any(overflow.values())
                return RenderResult(
                    html=html,
                    final_url=final_url,
                    metrics=metrics,
                    blocked_requests=blocked,
                    screenshots=screenshots,
                )
            finally:
                await browser.close()
