"""Async HTML fetcher (httpx + optional Playwright fallback) and local mock-site loader."""

from __future__ import annotations

import asyncio
import hashlib
import html
from datetime import datetime, timezone
import logging
import random
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.scraper.browser import BrowserRenderer, RenderResult
from app.scraper.ssrf import SSRFError, pinned_request, validate_public_url

logger = logging.getLogger("investwatch.scraper")

# URL shorteners whose redirect target is resolved (CRAWLER_EXPAND_SHORT_LINKS); link-in-bio pages
# (linktr.ee, ...) are fetched and their outbound links collected
SHORTENER_HOSTS = frozenset(
    {
        "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly",
        "shorturl.at", "t.ly", "s.id", "lnkd.in", "tiny.cc", "rb.gy",
    }
)
LINK_IN_BIO_HOSTS = frozenset({"linktr.ee", "beacons.ai", "lnk.bio", "bio.link", "linkin.bio", "taplink.cc"})
LINK_IN_BIO_MAX_BYTES = 524_288


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host

# Ethical, transparent User-Agent pool (no spoofing to bypass access controls)
ETHICAL_USER_AGENTS = [
    "InvestWatchResearchBot/1.0 (+https://knf.gov.pl; HackNation-UKNF-MVP) httpx/0.28",
    "InvestWatchComplianceMonitor/1.0 (Academic/Regulatory-Prototype) Python-httpx",
    "InvestWatchCrawler/1.0 (OpenSource-OnPremise-Prototype) Mozilla/5.0-compatible",
]


@dataclass
class HttpSnapshot:
    expires: float
    etag: str
    encoding: str
    data: bytes


@dataclass
class FetchedPage:
    source_url: str
    final_url: str
    source_platform: str
    raw_html: str
    status_code: int
    fetched_at: str | None = None
    payload_sha256: str | None = None
    redirect_chain: list[str] | None = None
    target_server_ip: str | None = None
    used_playwright: bool = False
    is_mock_source: bool = False
    playwright_dom_metrics: dict[str, object] | None = None
    # JPEG screenshots [desktop, mobile] from Playwright when OLLAMA_VISION_ENABLED=true
    screenshots: list[bytes] | None = None
    vision_findings: dict | None = None


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
        self._snapshots: OrderedDict[str, HttpSnapshot] = OrderedDict()
        self._renderer = BrowserRenderer(settings)

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
        current_url = await asyncio.to_thread(validate_public_url, url)
        await self._respect_rate_limit()

        headers = {
            "User-Agent": self.pick_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5",
        }

        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        chain = [str(current_url)]
        raw_bytes = bytearray()
        status_code = 200
        proxy = self.pick_proxy()

        async with asyncio.timeout(self.settings.crawler_timeout_seconds), httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, proxy=proxy, trust_env=False
        ) as client:
            for hop in range(self.settings.crawler_max_redirects + 1):
                current_url = await asyncio.to_thread(validate_public_url, current_url)
                cached = self._snapshots.get(current_url)
                if cached and cached.expires <= time.monotonic():
                    self._snapshots.pop(current_url)
                    cached = None
                request_headers = {**headers, "If-None-Match": cached.etag} if cached else headers
                async with client.stream("GET", **pinned_request(current_url, request_headers)) as resp:
                    status_code = resp.status_code
                    if status_code == 304 and cached:
                        raw_bytes.extend(cached.data)
                        encoding = cached.encoding
                        status_code = 200
                        break
                    if resp.is_redirect and "location" in resp.headers:
                        if hop >= self.settings.crawler_max_redirects:
                            raise SSRFError("Przekroczono maksymalną liczbę przekierowań HTTP.")
                        next_url = urljoin(current_url, resp.headers["location"])
                        chain.append(next_url)
                        current_url = await asyncio.to_thread(validate_public_url, next_url)
                        continue

                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "").lower()
                    if not any(
                        t in content_type for t in ("text/html", "text/plain", "application/xhtml")
                    ):
                        raise ValueError(f"Nieobsługiwany typ treści: {content_type}")

                    encoding = resp.encoding or "utf-8"
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        raw_bytes.extend(chunk)
                        if len(raw_bytes) > self.settings.crawler_max_bytes:
                            raise ValueError(
                                f"Przekroczono limit rozmiaru odpowiedzi ({self.settings.crawler_max_bytes} B)."
                            )
                    # Keep at most four bounded representations. Only strong ETags validate byte equality.
                    self._snapshots.pop(current_url, None)
                    etag = resp.headers.get("etag", "")
                    if etag.startswith('"') and "no-store" not in resp.headers.get("cache-control", "").lower() and not resp.headers.get("vary"):
                        self._snapshots[current_url] = HttpSnapshot(time.monotonic()+900, etag, encoding, bytes(raw_bytes))
                        if len(self._snapshots) > 4:
                            self._snapshots.popitem(last=False)
                    break

        try:
            html = raw_bytes.decode(encoding, errors="replace")
        except LookupError:
            html = raw_bytes.decode("utf-8", errors="replace")
        server_ip = getattr(current_url, "address", None) if not proxy else None
        pw_metrics: dict[str, object] | None = None
        screenshots: list[bytes] | None = None
        used_pw = False

        should_try_pw = use_playwright or (
            self.settings.crawler_use_playwright_fallback
            and self.looks_js_rendered(html, self.settings.crawler_playwright_min_text_chars)
        )
        if should_try_pw:
            rendered = await self._try_playwright_render(current_url, proxy=proxy)
            if rendered is not None:
                html = rendered.html
                current_url = rendered.final_url
                pw_metrics = rendered.metrics
                screenshots = rendered.screenshots or None
                used_pw = True

        return FetchedPage(
            source_url=url,
            final_url=current_url,
            source_platform=detect_platform_from_url(current_url),
            raw_html=html,
            status_code=status_code,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            payload_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            redirect_chain=chain, target_server_ip=server_ip,
            used_playwright=used_pw,
            is_mock_source=False,
            playwright_dom_metrics=pw_metrics,
            screenshots=screenshots,
        )

    @staticmethod
    def looks_js_rendered(html: str, min_text_chars: int) -> bool:
        """True when the HTML is an app shell: little visible text once scripts/styles are removed."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "noscript", "template", "svg"]):
            tag.decompose()
        return len(soup.get_text(" ", strip=True)) < min_text_chars

    async def _try_playwright_render(
        self, url: str, proxy: str | None = None
    ) -> RenderResult | None:
        """Optional Playwright fallback; any failure keeps the httpx result."""
        if not self._renderer.is_available():
            logger.info("Playwright nie jest zainstalowany — używam wyników httpx.")
            return None
        try:
            return await self._renderer.render(
                url,
                user_agent=self.pick_user_agent(),
                proxy=proxy,
                capture_screenshots=self.settings.ollama_vision_enabled,
            )
        except Exception as exc:
            logger.warning("Playwright fallback nie powiódł się dla %s: %s", url, exc)
            return None

    async def resolve_short_links(self, urls: list[str]) -> list[str]:
        """Resolve shortener / link-in-bio URLs to their destinations (anti-SSRF on every hop).

        Shorteners: the redirect chain is followed manually without downloading bodies.
        Link-in-bio pages: the page is fetched (size-capped) and its outbound links are returned.
        Failures are ignored — this only enriches the analysis.
        """
        candidates = [u for u in urls if _host(u) in SHORTENER_HOSTS | LINK_IN_BIO_HOSTS]
        candidates = candidates[: self.settings.crawler_expand_short_links_max]
        resolved: list[str] = []
        if not candidates:
            return resolved
        headers = {"User-Agent": self.pick_user_agent()}
        timeout = httpx.Timeout(self.settings.crawler_timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, proxy=self.pick_proxy(), trust_env=False
        ) as client:
            for url in candidates:
                try:
                    current = validate_public_url(url)
                    for _ in range(self.settings.crawler_max_redirects + 1):
                        await self._respect_rate_limit()
                        if _host(current) in LINK_IN_BIO_HOSTS:
                            resolved.extend(await self._link_in_bio_targets(client, current, headers))
                            break
                        async with client.stream("GET", **pinned_request(current, headers)) as resp:
                            location = resp.headers.get("location")
                            if not (resp.is_redirect and location):
                                if current != url:
                                    resolved.append(current)
                                break
                            current = validate_public_url(urljoin(current, location))
                except (SSRFError, httpx.HTTPError, ValueError) as exc:
                    logger.info("Nie rozwinięto linku %s: %s", url, exc)
        return list(dict.fromkeys(resolved))[:20]

    async def _link_in_bio_targets(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> list[str]:
        raw = bytearray()
        async with client.stream("GET", **pinned_request(url, headers)) as resp:
            if resp.status_code != 200:
                return []
            async for chunk in resp.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > LINK_IN_BIO_MAX_BYTES:
                    break
        soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
        own_host = _host(url)
        targets: list[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, str(a["href"]))
            if href.startswith(("http://", "https://")) and _host(href) and _host(href) != own_host:
                targets.append(href[:500])
        return targets[:10]
