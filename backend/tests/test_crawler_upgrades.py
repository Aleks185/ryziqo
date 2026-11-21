"""Tests for crawler upgrades: URL canonicalisation, robots.txt / per-host spacing, watchlist seed,
same-site link following, SearXNG discovery and the KNF registry refresh."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import discovery as discovery_module
from app.config import Settings
from app.discovery import SearchHit, build_queries, is_denied, rotate, search_names
from app.knf_registry import KNFRegistrySnapshot, pick_snapshot_path
from app.knf_sync import SourceResult, merge_snapshot, parse_csv, parse_html, write_snapshot_atomic
from app.main import create_app
from app.models import DomMetrics
from app.scraper import fetcher as fetcher_module
from app.scraper.fetcher import FetchedPage, PageFetcher
from app.scraper.links import extract_same_site_links
from app.scraper.politeness import HostRateLimiter, RobotsCache, RobotsDisallowedError
from app.scraper.urlnorm import canonicalize_url, site_key
from app.watchlist_seed import load_watchlist_seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "data_dir": str(DATA_DIR),
        "database_path": str(tmp_path / "t.db"),
        "object_store_dir": str(tmp_path / "store"),
        "ollama_base_url": "http://127.0.0.1:1",
        "crawler_enable_scheduler": False,
        "watchlist_seed_on_start": False,
        "crawler_per_host_delay_seconds": 0,
        "crawler_rate_limit_seconds": 0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _registry() -> KNFRegistrySnapshot:
    return KNFRegistrySnapshot(
        snapshot_path=DATA_DIR / "knf_registry_snapshot.json",
        rules_path=DATA_DIR / "risk_criteria_rules.json",
    )


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for job in client.get("/api/v1/crawl/jobs").json()["jobs"]:
            if job["job_id"] == job_id and job["status"] in ("completed", "failed"):
                return job
        time.sleep(0.2)
    raise AssertionError(f"Zadanie {job_id} nie zakończyło się w {timeout}s")


# --- URL canonicalisation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://WWW.Example.PL", "https://www.example.pl/"),
        ("https://example.pl/", "https://example.pl/"),
        ("https://example.pl/oferta/", "https://example.pl/oferta"),
        ("https://example.pl:443/a#sekcja", "https://example.pl/a"),
        ("http://example.pl:8080/a", "http://example.pl:8080/a"),
        ("https://example.pl/a?utm_source=fb&b=2&a=1&fbclid=x", "https://example.pl/a?a=1&b=2"),
        ("https://zażółć.pl/x", "https://xn--z-6ja2h4dc.pl/x"),
        ("mock://broker.html", "mock://broker.html"),
    ],
)
def test_canonicalize_url(raw: str, expected: str) -> None:
    got = canonicalize_url(raw)
    if "zażółć" in raw:
        assert got.startswith("https://xn--") and got.endswith(".pl/x")
    else:
        assert got == expected


def test_site_key_strips_www() -> None:
    assert site_key("https://www.XTB.com/pl") == "xtb.com"


def test_watchlist_rejects_duplicate_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import watchlist as watchlist_router

    monkeypatch.setattr(watchlist_router, "validate_public_url", lambda u: u)
    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        first = client.post("/api/v1/watchlist", json={"url": "https://x.pl"})
        assert first.status_code == 201
        assert first.json()["url"] == "https://x.pl/"
        dup = client.post("/api/v1/watchlist", json={"url": "https://X.pl/?utm_source=a"})
        assert dup.status_code == 409


# --- robots.txt and per-host spacing ------------------------------------------------


def test_robots_cache_rules_crawl_delay_and_errors() -> None:
    calls: list[str] = []

    async def loader(url: str) -> tuple[int, str]:
        calls.append(url)
        if "down" in url:
            return 503, ""
        if "missing" in url:
            return 404, ""
        return 200, "User-agent: InvestWatch\nDisallow: /prywatne\nCrawl-delay: 3\n\nUser-agent: *\nDisallow: /\n"

    cache = RobotsCache(loader, ttl_seconds=3600)
    ua = "InvestWatchCrawler/1.0 (OpenSource-OnPremise-Prototype)"

    async def run() -> None:
        assert await cache.can_fetch(ua, "https://site.pl/oferta")
        assert not await cache.can_fetch(ua, "https://site.pl/prywatne/a")
        assert not await cache.can_fetch("OtherBot/1.0", "https://site.pl/oferta")
        assert await cache.crawl_delay(ua, "https://site.pl/") == 3.0
        assert await cache.can_fetch(ua, "https://down.pl/x")
        assert await cache.can_fetch(ua, "https://missing.pl/x")

    asyncio.run(run())
    assert calls.count("https://site.pl/robots.txt") == 1, "robots.txt powinien być cache'owany"


def test_host_rate_limiter_spaces_same_host_only() -> None:
    clock = [100.0]
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    limiter = HostRateLimiter(clock=lambda: clock[0])

    async def run() -> None:
        original = asyncio.sleep
        asyncio.sleep = fake_sleep  # type: ignore[assignment]
        try:
            await limiter.wait("a.pl", 2.0)
            await limiter.wait("b.pl", 2.0)
            clock[0] += 0.5
            await limiter.wait("a.pl", 2.0)
        finally:
            asyncio.sleep = original  # type: ignore[assignment]

    asyncio.run(run())
    assert slept == [pytest.approx(1.5)]


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    real_client = httpx.AsyncClient

    class MockClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            kwargs.pop("proxy", None)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", MockClient)
    monkeypatch.setattr(fetcher_module, "validate_public_url", lambda u: u)


def test_fetcher_honours_robots_disallow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /tajne\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>ok</p>")

    _mock_http(monkeypatch, handler)
    fetcher = PageFetcher(_settings(tmp_path))
    assert asyncio.run(fetcher.fetch_public_url("https://site.pl/jawne")).raw_html == "<p>ok</p>"
    with pytest.raises(RobotsDisallowedError):
        asyncio.run(fetcher.fetch_public_url("https://site.pl/tajne/1"))
    off = PageFetcher(_settings(tmp_path, crawler_respect_robots=False))
    assert asyncio.run(off.fetch_public_url("https://site.pl/tajne/1")).status_code == 200


def test_robots_disallowed_job_completes_with_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import crawl as crawl_router

    async def blocked(url: str, use_playwright: bool = False) -> FetchedPage:
        raise RobotsDisallowedError(url)

    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        monkeypatch.setattr(crawl_router, "validate_public_url", lambda u: u)
        monkeypatch.setattr(client.app.state.fetcher, "fetch_public_url", blocked)
        resp = client.post("/api/v1/crawl/trigger", json={"mode": "public_url", "target_url": "https://site.pl/x"})
        job = _wait_for_job(client, resp.json()["job_id"])
        assert job["status"] == "completed"
        assert job["error_message"] == "robots.txt disallow"


# --- Rule 8: tablet viewport --------------------------------------------------------


def test_rule8_reports_overflowing_viewports() -> None:
    from app.ai.preprocessor import preprocess_html

    doc = preprocess_html(
        raw_html="<html><body><p>Inwestuj w CFD</p></body></html>",
        source_url="https://site.pl",
        source_platform="web",
        is_mock_source=False,
        playwright_metrics={
            "responsive_overflow_detected": True,
            "responsive_overflow_by_viewport": {"tablet": True, "mobile": False},
        },
    )
    assert doc.dom_metrics.responsive_overflow_detected
    assert doc.dom_metrics.responsive_overflow_viewports == ["tablet"]
    assert DomMetrics().responsive_overflow_viewports == []


# --- Watchlist seed -----------------------------------------------------------------


def test_watchlist_seed_includes_registry_domains_without_synthetic() -> None:
    items = load_watchlist_seed(DATA_DIR / "watchlist_seed.json", _registry())
    urls = [i["url"] for i in items]
    assert len({site_key(u) for u in urls}) == len(urls), "jedna domena = jeden cel"
    assert any("xtb.com" in u for u in urls)
    assert not any("nordicmarkets" in u.lower() for u in urls)


def test_watchlist_seeded_once_on_start(tmp_path: Path) -> None:
    settings = _settings(tmp_path, watchlist_seed_on_start=True)
    with TestClient(create_app(custom_settings=settings)) as client:
        count = len(client.get("/api/v1/watchlist").json()["items"])
        assert count >= 4
        again = client.post("/api/v1/watchlist/seed").json()
        assert again == {"added": 0, "total": count}
    with TestClient(create_app(custom_settings=settings)) as client:
        assert len(client.get("/api/v1/watchlist").json()["items"]) == count


# --- Link following -----------------------------------------------------------------


def test_extract_same_site_links_prioritises_risk_pages() -> None:
    html = """
      <a href="/blog/1">Blog</a>
      <a href="https://www.site.pl/regulamin/">Regulamin</a>
      <a href="https://inna.pl/x">obca</a>
      <a href="/plik.pdf">PDF</a>
      <a href="#top">top</a>
      <a href="/?utm_source=x">home</a>
      <a href="/blog/1#c">dup</a>
    """
    links = extract_same_site_links(html, "https://site.pl/")
    assert links == ["https://www.site.pl/regulamin", "https://site.pl/blog/1"]


def test_public_url_job_follows_same_site_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import crawl as crawl_router

    pages = {
        "https://site.pl/": '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="https://obca.pl/">X</a>',
        "https://site.pl/a": '<a href="/a/1">A1</a><p>a</p>',
        "https://site.pl/b": "<p>b</p>",
        "https://site.pl/c": "<p>c</p>",
        "https://site.pl/a/1": "<p>a1</p>",
    }
    fetched: list[str] = []

    async def fake_fetch(url: str, use_playwright: bool = False) -> FetchedPage:
        fetched.append(url)
        return FetchedPage(url, url, "web", pages[canonicalize_url(url)], 200)

    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        monkeypatch.setattr(crawl_router, "validate_public_url", lambda u: u)
        monkeypatch.setattr(client.app.state.fetcher, "fetch_public_url", fake_fetch)
        body = {"mode": "public_url", "target_url": "https://site.pl/", "follow_depth": 1, "follow_max_pages": 3}
        job = _wait_for_job(client, client.post("/api/v1/crawl/trigger", json=body).json()["job_id"])
        assert job["status"] == "completed"
        assert job["processed_count"] == 3
        assert fetched == ["https://site.pl/", "https://site.pl/a", "https://site.pl/b"]

        # The trigger fetches the canonical URL (tracking parameters dropped)
        fetched.clear()
        body = {"mode": "public_url", "target_url": "https://Site.pl/c?utm_source=x&fbclid=y"}
        job = _wait_for_job(client, client.post("/api/v1/crawl/trigger", json=body).json()["job_id"])
        assert job["status"] == "completed"
        assert fetched == ["https://site.pl/c"]


# --- Discovery (SearXNG) ------------------------------------------------------------


def test_query_building_and_rotation() -> None:
    names = search_names(_registry())
    assert "XTB" in names and not any("Nordic" in n for n in names)
    queries = build_queries(["XTB", "eToro"], {"entity_templates": ["{name} kod"], "generic_queries": ["g"]})
    assert queries == ["XTB kod", "eToro kod", "g"]
    batch, nxt = rotate(queries, 2, 2)
    assert batch == ["g", "XTB kod"] and nxt == 1
    assert is_denied("https://www.knf.gov.pl/x", ["gov.pl"])
    assert not is_denied("https://notgov.pl/x", ["gov.pl"])


class _FakeSearx:
    def __init__(self, hits: list[SearchHit] | Exception) -> None:
        self.hits = hits
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        self.queries.append(query)
        if isinstance(self.hits, Exception):
            raise self.hits
        return self.hits


def test_discovery_enqueues_filters_and_dedups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_validate(url: str) -> str:
        if "127.0.0.1" in url:
            from app.scraper.ssrf import SSRFError

            raise SSRFError("private")
        return url

    monkeypatch.setattr(discovery_module, "validate_public_url", fake_validate)
    settings = _settings(
        tmp_path,
        discovery_enabled=True,
        discovery_queries_per_run=2,
        discovery_max_new_urls_per_run=2,
    )
    hits = [
        SearchHit("https://promo.example/xtb?utm_source=a", "Promo", "duckduckgo"),
        SearchHit("https://promo.example/xtb", "Promo dup", "bing"),
        SearchHit("https://www.knf.gov.pl/ostrzezenia", "KNF", "bing"),
        SearchHit("http://127.0.0.1/admin", "internal", "bing"),
        SearchHit("https://kurs.example/vip", "Kurs", "bing"),
        SearchHit("https://trzeci.example/", "Trzeci", "bing"),
    ]
    with TestClient(create_app(custom_settings=settings)) as client:
        worker = client.app.state.worker
        fake = _FakeSearx(hits)
        worker.discovery.client = fake

        first = client.post("/api/v1/discovery/run")
        assert first.status_code == 202
        data = first.json()
        assert len(fake.queries) == 2
        assert data["enqueued"] == ["https://promo.example/xtb", "https://kurs.example/vip"]
        assert data["rejected"] == 2  # denylist + SSRF
        jobs = client.get("/api/v1/crawl/jobs").json()["jobs"]
        assert {j["origin"] for j in jobs if j["job_id"] in data["job_ids"]} == {"discovery"}

        second = client.post("/api/v1/discovery/run").json()
        assert second["enqueued"] == ["https://trzeci.example/"], "trzeci URL czekał na limit poprzedniego runu"
        assert second["skipped_seen"] == 2
        recent = client.get("/api/v1/discovery/recent").json()
        assert recent["enabled"] is True
        assert {i["url"] for i in recent["items"]} >= {"https://promo.example/xtb", "https://trzeci.example/"}


def test_discovery_survives_searxng_outage_and_is_off_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        assert client.post("/api/v1/discovery/run").status_code == 409
    settings = _settings(tmp_path, discovery_enabled=True)
    with TestClient(create_app(custom_settings=settings)) as client:
        client.app.state.worker.discovery.client = _FakeSearx(httpx.ConnectError("down"))
        data = client.post("/api/v1/discovery/run").json()
        assert data["enqueued"] == [] and data["error"].startswith("SearXNG")


# --- KNF registry refresh -----------------------------------------------------------


def test_parse_html_table_list_and_file_links() -> None:
    table = """<table><tr><th>Lp.</th><th>Nazwa podmiotu</th><th>Adres</th></tr>
      <tr><td>1</td><td>XTB S.A.</td><td>Warszawa</td></tr>
      <tr><td>2</td><td>Nowy Dom Maklerski S.A.</td><td>Kraków</td></tr></table>
      <a href="/files/lista.xlsx">pobierz</a>"""
    names, files = parse_html(table, "https://www.knf.gov.pl/podmioty/x")
    assert names == ["XTB S.A.", "Nowy Dom Maklerski S.A."]
    assert files == ["https://www.knf.gov.pl/files/lista.xlsx"]

    lists = "<ul><li>Menu</li><li>1. Alfa Investments Ltd.</li><li>Beta Securities S.A.</li></ul>"
    assert parse_html(lists, "https://knf.gov.pl/")[0] == ["Alfa Investments Ltd.", "Beta Securities S.A."]
    assert parse_csv("Lp;Nazwa\n1;Gamma AG\n2;Delta A/S\n") == ["Gamma AG", "Delta A/S"]


def test_merge_snapshot_keeps_aliases_synthetic_and_applies_safety_net() -> None:
    old = json.loads((DATA_DIR / "knf_registry_snapshot.json").read_text(encoding="utf-8"))
    results = [
        SourceResult("domy_maklerskie", "u", names=["XTB S.A.", "Nowy Dom Maklerski S.A.", "Dom Maklerski BOŚ S.A."]),
        SourceResult("banki_maklerskie", "u", names=[]),
        SourceResult("zagraniczne_bez_oddzialu", "u", error="ECONNRESET"),
    ]
    doc, report = merge_snapshot(old, results, today="2026-12-01")
    by_name = {e["official_name"]: e for e in doc["entities"]}

    assert doc["snapshot_date"] == "2026-12-01"
    assert by_name["XTB S.A."]["aliases"] == ["XTB", "X-Trade Brokers", "xtb.com"]
    assert by_name["Nowy Dom Maklerski S.A."]["registry_status"] == "registered_pl"
    # Curated entries (manual aliases) are never dropped — KNF spells names differently
    assert report.unmatched_kept["dom_maklerski"] == ["TMS Brokers (OANDA TMS Brokers S.A.)"]
    assert "TMS Brokers (OANDA TMS Brokers S.A.)" in by_name
    assert "dom_maklerski" not in report.removed
    assert any(e["is_synthetic_demo"] and e["category"] == "dom_maklerski" for e in doc["entities"])
    assert "bank_maklerski" in report.kept_old
    assert "Biuro Maklerskie mBanku" in by_name
    assert report.errors == {"zagraniczna_bez_oddzialu": "ECONNRESET"}
    assert "Saxo Bank A/S (notyfikacja transgraniczna)" in by_name


def test_refreshed_snapshot_is_picked_and_reload_updates_matching(tmp_path: Path) -> None:
    seed = DATA_DIR / "knf_registry_snapshot.json"
    live = tmp_path / "knf_registry_snapshot.json"
    assert pick_snapshot_path(seed, live) == seed

    doc = json.loads(seed.read_text(encoding="utf-8"))
    doc["snapshot_date"] = "2999-01-01"
    doc["entities"].append(
        {
            "official_name": "Zupełnie Nowy Broker S.A.",
            "aliases": ["ZupelnieNowyBroker"],
            "category": "dom_maklerski",
            "registry_status": "registered_pl",
            "country": "PL",
            "is_synthetic_demo": False,
        }
    )
    write_snapshot_atomic(live, doc)
    assert pick_snapshot_path(seed, live) == live

    registry = _registry()
    assert registry.match_entity_in_text("Konto w ZupelnieNowyBroker") is None
    registry.reload(live)
    match = registry.match_entity_in_text("Konto w ZupelnieNowyBroker")
    assert match is not None and match.official_name == "Zupełnie Nowy Broker S.A."
    assert registry.snapshot_date == "2999-01-01"


# --- Rules 6/7: a warning repeated in the footer is not a hidden warning ------------------
RISK = "Kontrakty CFD są złożonymi instrumentami i wiążą się z dużym ryzykiem utraty środków."


@pytest.mark.parametrize(
    ("body", "footer", "details"),
    [
        (f"<header><p>{RISK}</p></header><main><p>Oferta</p></main><footer><p>{RISK}</p></footer>", False, False),
        (f"<div class='page'><main><p>Oferta</p></main><footer><p>{RISK}</p></footer></div>", True, False),
        (f"<main><p>Oferta</p><details><summary>Ryzyko</summary><p>{RISK}</p></details></main>", False, True),
        (f"<p>{RISK}</p><details><summary>Więcej</summary><p>{RISK}</p></details>", False, False),
        (f"<p>{RISK}</p><div style='display:none'><p>{RISK}</p></div>", False, False),
    ],
)
def test_rules_6_7_require_risk_to_be_exclusively_hidden(body: str, footer: bool, details: bool) -> None:
    from app.ai.preprocessor import preprocess_html

    doc = preprocess_html(f"<html><body>{body}</body></html>", "https://broker.pl/", "web")
    assert doc.dom_metrics.risk_hidden_in_footer is footer
    assert doc.dom_metrics.requires_click_to_view_risk is details


KNF_PAGE = """<nav><a href="/podmioty/lista?page=2">2</a><a href="/podmioty/lista?page=3">3</a>
<a href="/podmioty/inna?page=9">inna lista</a><a href="http://[zepsuty">x</a></nav>
<table><tr><th>Nazwa</th><td><span>CERES DOM INWESTYCYJNY S.A.<br/><strike>EFIX DOM MAKLERSKI S.A.</strike></span></td></tr>
<tr><th>Data zezwolenia</th><td>26-05-2010</td></tr></table>
<table><tr><th>Nazwa</th><td><span>BANK PEKAO S.A.<strike> <br />B</strike>iuro Maklerskie PEKAO</span></td></tr>
<tr><th>Zakres działalności</th><td>1, 2</td></tr></table>"""


def test_parse_knf_key_value_tables_and_pagination() -> None:
    from app.knf_sync import page_count

    names, _ = parse_html(KNF_PAGE, "https://www.knf.gov.pl/podmioty/lista")
    assert names == ["CERES DOM INWESTYCYJNY S.A.", "BANK PEKAO S.A. Biuro Maklerskie PEKAO"]
    assert page_count(KNF_PAGE, "https://www.knf.gov.pl/podmioty/lista") == 3


def test_fetch_source_walks_pages_with_browser_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import knf_sync

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["user-agent"]))
        page = request.url.params.get("page", "1")
        if page == "1":
            return httpx.Response(200, text=KNF_PAGE)
        return httpx.Response(200, text=f"<table><tr><th>Nazwa podmiotu</th><td>Firma {page} Ltd</td></tr></table>")

    monkeypatch.setattr(knf_sync, "validate_public_url", lambda u: u)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        knf_sync.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    settings = Settings(crawler_per_host_delay_seconds=0, knf_sync_user_agent="")
    sources = {"domy_maklerskie": "https://www.knf.gov.pl/podmioty/lista"}
    results = asyncio.run(knf_sync.fetch_official_sources(settings, sources))

    assert results[0].error is None
    assert results[0].names[-2:] == ["Firma 2 Ltd", "Firma 3 Ltd"]
    assert [u for u, _ in seen][1:] == [
        "https://www.knf.gov.pl/podmioty/lista?page=2",
        "https://www.knf.gov.pl/podmioty/lista?page=3",
    ]
    # Empty setting (unset in docker compose) falls back to the browser User-Agent
    assert all(ua.startswith("Mozilla/5.0") for _, ua in seen)


def test_imported_registry_names_do_not_create_lookalike_alarms(tmp_path: Path) -> None:
    doc = json.loads((DATA_DIR / "knf_registry_snapshot.json").read_text(encoding="utf-8"))
    for name in ("Lago Kapital Ltd", "Monex Europe Markets, S.V, S.A", "Investium Limited"):
        doc["entities"].append(
            {"official_name": name, "aliases": [], "category": "zagraniczna_bez_oddzialu",
             "registry_status": "registered_eu_crossborder", "country": "EU", "is_synthetic_demo": False}
        )
    path = tmp_path / "knf_registry_snapshot.json"
    write_snapshot_atomic(path, doc)
    reg = KNFRegistrySnapshot(snapshot_path=path, rules_path=DATA_DIR / "risk_criteria_rules.json")

    legit = ["https://capital.com/", "https://www.money.pl/", "https://investing.com/", "https://www.mbank.pl/"]
    assert reg.find_impersonations("", legit) == []
    assert reg.find_impersonations("", ["https://bosssa.pl/"])[0].kind == "typosquat"  # curated brands still guarded
    assert reg.match_entity_in_text("Oferta Lago Kapital Ltd dla klientów z Polski") is not None
