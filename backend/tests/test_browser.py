"""Playwright renderer: JS-rendered pages, computed-style DOM metrics and browser anti-SSRF.

Skipped automatically when Playwright or its Chromium build is not installed
(`pip install -r requirements-playwright.txt && playwright install chromium`).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.ai.preprocessor import preprocess_html
from app.config import Settings
from app.scraper import browser as browser_module
from app.scraper import fetcher as fetcher_module
from app.scraper import ssrf
from app.scraper.browser import BrowserRenderer, playwright_proxy_config
from app.scraper.fetcher import PageFetcher

playwright_api = pytest.importorskip("playwright.async_api")

STYLE_CSS = """
body { font-size: 16px; color: #111111; background: #ffffff; }
.hero { font-size: 20px; }
.legal .risk { font-size: 9px; color: #c8c8c8; }
.wide { width: 900px; white-space: nowrap; }
"""

# App shell: no visible text until JavaScript runs. It also tries to reach internal addresses.
SPA_HTML = """<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>Alpha CFD — promocja</title><link rel="stylesheet" href="/style.css"></head>
<body><div id="root"></div>
<script src="http://169.254.169.254/latest/meta-data/x.js"></script>
<script src="/redirect-internal"></script>
<script>
  document.getElementById('root').innerHTML =
    '<p class="hero">Zarabiaj nawet 40% rocznie na kontraktach na złoto i ropę. Otwórz rachunek w 2 minuty ' +
    'i dołącz do tysięcy zadowolonych inwestorów, którzy już korzystają z naszej platformy transakcyjnej.</p>' +
    '<div class="wide">Tabela wyników naszych klientów z ostatniego kwartału</div>' +
    '<footer class="legal"><p class="risk">CFD są złożonymi instrumentami i wiążą się z wysokim ' +
    'ryzykiem utraty kapitału.</p></footer>';
  fetch('http://10.0.0.1/internal').catch(() => {});
  try { new WebSocket('ws://127.0.0.1:1/socket'); } catch (e) {}
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        routes = {
            "/spa": ("text/html; charset=utf-8", SPA_HTML),
            "/style.css": ("text/css", STYLE_CSS),
        }
        redirects = {
            "/redirect-internal": "http://169.254.169.254/latest/meta-data/",
            "/redirect-ok": "/spa",
        }
        if self.path in redirects:
            self.send_response(302)
            self.send_header("Location", redirects[self.path])
            self.end_headers()
            return
        if self.path not in routes:
            self.send_response(404)
            self.end_headers()
            return
        ctype, body = routes[self.path]
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def origin() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module", autouse=True)
def _require_chromium() -> None:
    async def _probe() -> None:
        async with playwright_api.async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()

    try:
        asyncio.run(_probe())
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Chromium dla Playwright niedostępny: {exc}")


@pytest.fixture
def allow_test_origin(origin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow exactly the local test server; every other URL goes through the real anti-SSRF check."""
    real = ssrf.validate_public_url

    def validate(url: str) -> str:
        if url == origin or url.startswith(origin + "/"):
            return url
        return real(url)

    monkeypatch.setattr(browser_module, "validate_public_url", validate)
    monkeypatch.setattr(fetcher_module, "validate_public_url", validate)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_path": str(tmp_path / "t.db"),
        "object_store_dir": str(tmp_path / "store"),
        "crawler_rate_limit_seconds": 0,
        "crawler_playwright_timeout_seconds": 15,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_render_computes_styles_and_blocks_internal_requests(
    tmp_path: Path, origin: str, allow_test_origin: None
) -> None:
    renderer = BrowserRenderer(_settings(tmp_path))
    result = asyncio.run(renderer.render(f"{origin}/spa", user_agent="InvestWatchTest/1.0"))

    assert "złożonymi instrumentami" in result.html
    assert result.final_url == f"{origin}/spa"
    computed = result.metrics["computed"]
    assert computed["risk_font_px"] == 9
    assert computed["dominant_font_px"] == 20
    assert computed["low_contrast_detected"] is True and computed["risk_min_contrast"] < 4.5
    assert computed["risk_hidden_in_footer"] is True
    assert result.metrics["responsive_overflow_detected"] is True
    # metadata script, redirected script, fetch() to 10.0.0.1 and WebSocket to loopback were refused
    assert result.blocked_requests >= 4


def test_render_refuses_redirect_to_internal_address(
    tmp_path: Path, origin: str, allow_test_origin: None
) -> None:
    renderer = BrowserRenderer(_settings(tmp_path))
    # Must be refused by our route guard, not merely fail to connect
    with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
        asyncio.run(renderer.render(f"{origin}/redirect-internal", user_agent="InvestWatchTest/1.0"))


def test_render_follows_allowed_redirect(tmp_path: Path, origin: str, allow_test_origin: None) -> None:
    renderer = BrowserRenderer(_settings(tmp_path))
    result = asyncio.run(renderer.render(f"{origin}/redirect-ok", user_agent="InvestWatchTest/1.0"))
    assert "złożonymi instrumentami" in result.html
    assert result.metrics["computed"]["risk_font_px"] == 9


def test_fetcher_falls_back_to_browser_for_app_shell_and_feeds_dom_metrics(
    tmp_path: Path, origin: str, allow_test_origin: None
) -> None:
    fetcher = PageFetcher(_settings(tmp_path, crawler_use_playwright_fallback=True))
    page = asyncio.run(fetcher.fetch_public_url(f"{origin}/spa"))

    assert page.used_playwright is True
    assert "Zarabiaj nawet 40%" in page.raw_html

    doc = preprocess_html(
        raw_html=page.raw_html,
        source_url=page.source_url,
        source_platform=page.source_platform,
        playwright_metrics=page.playwright_dom_metrics,
    )
    assert "ryzykiem utraty kapitału" in doc.normalized_text
    assert doc.dom_metrics.risk_font_px == 9.0
    assert doc.dom_metrics.font_ratio == 0.45
    assert doc.dom_metrics.low_contrast_detected is True
    assert doc.dom_metrics.risk_hidden_in_footer is True
    assert doc.dom_metrics.responsive_overflow_detected is True


def test_fetcher_skips_browser_for_server_rendered_page(tmp_path: Path) -> None:
    html = "<html><body>" + "<p>Treść artykułu renderowana po stronie serwera.</p>" * 20 + "</body></html>"
    assert PageFetcher.looks_js_rendered(html, 400) is False
    assert PageFetcher.looks_js_rendered(SPA_HTML, 400) is True


def test_playwright_proxy_config() -> None:
    assert playwright_proxy_config(None) is None
    assert playwright_proxy_config("http://proxy:3128") == {"server": "http://proxy:3128"}
    assert playwright_proxy_config("socks5://us%40er:p%3Ass@proxy:1080") == {
        "server": "socks5://proxy:1080",
        "username": "us@er",
        "password": "p:ss",
    }
    with pytest.raises(ValueError):
        playwright_proxy_config("not-a-proxy")
