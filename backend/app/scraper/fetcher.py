"""Async HTML fetcher (httpx + optional Playwright fallback) and local mock-site loader."""

from __future__ import annotations

import asyncio
import html
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings
from app.scraper.ssrf import SSRFError, validate_public_url

logger = logging.getLogger("investwatch.scraper")

# Ethical, transparent User-Agent pool (no spoofing to bypass access controls)
ETHICAL_USER_AGENTS = [
    "InvestWatchResearchBot/1.0 (+https://knf.gov.pl; HackNation-UKNF-MVP) httpx/0.28",
    "InvestWatchComplianceMonitor/1.0 (Academic/Regulatory-Prototype) Python-httpx",
    "InvestWatchCrawler/1.0 (OpenSource-OnPremise-Prototype) Mozilla/5.0-compatible",
]


@dataclass
class FetchedPage:
    source_url: str
    final_url: str
    source_platform: str
    raw_html: str
    status_code: int
    used_playwright: bool = False
    is_mock_source: bool = False
    playwright_dom_metrics: dict[str, object] | None = None


def build_manual_text_page(content: str, title: str | None, source_url: str | None) -> FetchedPage:
    """Wrap analyst-pasted plain text into a minimal HTML page for the shared pipeline.

    The text is HTML-escaped, so pasted markup is treated as data, never rendered or executed.
    Nothing is fetched from the network.
    """
    paragraphs = [p.strip() for p in content.replace("\r\n", "\n").split("\n\n") if p.strip()]
    body = "\n".join(f"<p>{html.escape(p)}</p>" for p in paragraphs) or "<p></p>"
    title_html = f"<title>{html.escape(title.strip())}</title>" if title and title.strip() else ""
    raw_html = f'<!doctype html><html lang="pl"><head><meta charset="utf-8">{title_html}</head><body>{body}</body></html>'
    url = (source_url or "").strip() or "manual://text"
    return FetchedPage(
        source_url=url,
        final_url=url,
        source_platform="manual",
        raw_html=raw_html,
        status_code=200,
    )


def detect_platform_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "tiktok" in host:
        return "tiktok"
    if "instagram" in host:
        return "instagram"
    if "facebook" in host or "fb.com" in host:
        return "facebook"
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if host in ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"):
        return "x"
    return "web"


class PageFetcher:
    """Safe async fetcher with rate limiting, size caps, redirect SSRF checks, and mock support."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_public_request_ts: float = 0.0
        self._rate_lock = asyncio.Lock()

    async def _respect_rate_limit(self) -> None:
        async with self._rate_lock:
            now = asyncio.get_running_loop().time()
            elapsed = now - self._last_public_request_ts
            wait = self.settings.crawler_rate_limit_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_public_request_ts = asyncio.get_running_loop().time()

    def pick_proxy(self) -> str | None:
        """Rotate configured proxies per request (CRAWLER_PROXIES); None means a direct connection."""
        proxies = self.settings.crawler_proxy_list
        return random.choice(proxies) if proxies else None

    @staticmethod
    def pick_user_agent() -> str:
        return random.choice(ETHICAL_USER_AGENTS)

    def list_mock_files(self) -> list[str]:
        mock_dir = self.settings.mock_sites_dir
        if not mock_dir.exists():
            return []
        return sorted(p.name for p in mock_dir.glob("*.html") if p.is_file())

    async def fetch_mock_page(self, filename: str) -> FetchedPage:
        """Load a static local mock HTML file safely (preventing path traversal)."""
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.endswith(".html"):
            raise ValueError(f"Nieprawidłowa nazwa pliku mock: '{filename}'.")

        file_path = (self.settings.mock_sites_dir / safe_name).resolve()
        if not str(file_path).startswith(str(self.settings.mock_sites_dir.resolve())):
            raise ValueError("Wykryto próbę wyjścia poza katalog mock_sites.")
        if not file_path.exists():
            raise FileNotFoundError(f"Plik mock '{safe_name}' nie istnieje.")

        raw_html = file_path.read_text(encoding="utf-8")
        platform = "web"
        if "tiktok" in safe_name:
            platform = "tiktok"
        elif "instagram" in safe_name:
            platform = "instagram"
        elif "facebook" in safe_name:
            platform = "facebook"
        elif "youtube" in safe_name or "edu" in safe_name:
            platform = "youtube"

        return FetchedPage(
            source_url=f"mock://{safe_name}",
            final_url=f"mock://{safe_name}",
            source_platform=platform,
            raw_html=raw_html,
            status_code=200,
            used_playwright=False,
            is_mock_source=True,
        )

    async def fetch_public_url(self, url: str, use_playwright: bool = False) -> FetchedPage:
        """Fetch a public HTTP(S) page with strict anti-SSRF validation on every redirect."""
        current_url = validate_public_url(url)
        await self._respect_rate_limit()

        headers = {
            "User-Agent": self.pick_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
        }

        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        raw_bytes = bytearray()
        status_code = 200
        proxy = self.pick_proxy()

        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, proxy=proxy, trust_env=False
        ) as client:
            for hop in range(self.settings.crawler_max_redirects + 1):
                validate_public_url(current_url)
                async with client.stream("GET", current_url, headers=headers) as resp:
                    status_code = resp.status_code
                    if resp.is_redirect and "location" in resp.headers:
                        if hop >= self.settings.crawler_max_redirects:
                            raise SSRFError("Przekroczono maksymalną liczbę przekierowań HTTP.")
                        next_url = urljoin(current_url, resp.headers["location"])
                        current_url = validate_public_url(next_url)
                        continue

                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "").lower()
                    if content_type and not any(
                        t in content_type for t in ("text/html", "text/plain", "application/xhtml")
                    ):
                        raise ValueError(f"Nieobsługiwany typ treści: {content_type}")

                    async for chunk in resp.aiter_bytes():
                        raw_bytes.extend(chunk)
                        if len(raw_bytes) > self.settings.crawler_max_bytes:
                            raise ValueError(
                                f"Przekroczono limit rozmiaru odpowiedzi ({self.settings.crawler_max_bytes} B)."
                            )
                    break

        html = raw_bytes.decode("utf-8", errors="replace")
        pw_metrics: dict[str, object] | None = None
        used_pw = False

        should_try_pw = use_playwright or (
            self.settings.crawler_use_playwright_fallback and len(html.strip()) < 600
        )
        if should_try_pw:
            pw_html, pw_metrics = await self._try_playwright_render(current_url, proxy=proxy)
            if pw_html:
                html = pw_html
                used_pw = True

        return FetchedPage(
            source_url=url,
            final_url=current_url,
            source_platform=detect_platform_from_url(current_url),
            raw_html=html,
            status_code=status_code,
            used_playwright=used_pw,
            is_mock_source=False,
            playwright_dom_metrics=pw_metrics,
        )

    async def _try_playwright_render(
        self, url: str, proxy: str | None = None
    ) -> tuple[str | None, dict[str, object] | None]:
        """Optional Playwright fallback for JS-rendered pages + responsive viewport check."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.info("Playwright nie jest zainstalowany — używam wyników httpx.")
            return None, None

        try:
            validate_public_url(url)
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True, proxy={"server": proxy} if proxy else None
                )
                try:
                    page = await browser.new_page(
                        viewport={"width": 1280, "height": 800},
                        user_agent=self.pick_user_agent(),
                    )

                    # Anti-SSRF for the browser: every request (redirects, sub-resources) is re-validated
                    async def _guard(route) -> None:  # type: ignore[no-untyped-def]
                        req_url = route.request.url
                        try:
                            if not req_url.startswith(("data:", "blob:")):
                                validate_public_url(req_url)
                        except SSRFError:
                            await route.abort()
                            return
                        await route.continue_()

                    await page.route("**/*", _guard)
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    html = await page.content()

                    # Check mobile viewport overflow (Rule 8 — Responsiveness)
                    await page.set_viewport_size({"width": 375, "height": 667})
                    overflow_mobile = await page.evaluate(
                        "() => document.documentElement.scrollWidth > window.innerWidth + 10"
                    )
                    return html, {"responsive_overflow_detected": bool(overflow_mobile)}
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("Playwright fallback nie powiódł się dla %s: %s", url, exc)
            return None, None
