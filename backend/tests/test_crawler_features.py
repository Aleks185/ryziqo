"""Tests for social parsers, proxy rotation, persistent queue, watchlist, near-dup, reports, risk_level."""

from __future__ import annotations

import asyncio
import csv
import io
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.main import create_app
from app.scraper import fetcher as fetcher_module
from app.scraper.fetcher import FetchedPage, PageFetcher
from app.scraper.social_parsers import handle_from_url, parse_social_post

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
MOCK_DIR = DATA_DIR / "mock_sites"


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "data_dir": str(DATA_DIR),
        "database_path": str(tmp_path / "test_investwatch.db"),
        "object_store_dir": str(tmp_path / "object_store"),
        "ollama_base_url": "http://127.0.0.1:1",
        "crawler_enable_scheduler": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for job in client.get("/api/v1/crawl/jobs").json()["jobs"]:
            if job["job_id"] == job_id and job["status"] in ("completed", "failed"):
                return job
        time.sleep(0.2)
    raise AssertionError(f"Zadanie {job_id} nie zakończyło się w {timeout}s")


# --- Social-media parsers -----------------------------------------------------------


def test_parse_tiktok_mock_reads_jsonld_author_date_and_hashtags() -> None:
    html = (MOCK_DIR / "finfluencer_tiktok_cfd.html").read_text(encoding="utf-8")
    post = parse_social_post(html, "mock://finfluencer_tiktok_cfd.html", "tiktok")
    assert post.author_handle == "@krypto_luksus_pl"
    assert post.author_name == "Krypto Luksus PL"
    assert post.published_at == "2026-11-18T19:42:00Z"
    assert "cfd" in [h.lower() for h in post.hashtags]
    assert "json-ld" in post.extraction_sources
    assert post.post_text and "LUKSUS100" in post.post_text


def test_parse_generic_post_uses_opengraph_url_handle_and_text_markers() -> None:
    html = """<html><head>
      <meta property="og:description" content="Wpadajcie na live! #reklama #forex z @broker_pl">
    </head><body><p>Link: <a href="https://broker.example/ref?c=1">broker</a>
      <a href="/local">local</a></p></body></html>"""
    post = parse_social_post(html, "https://www.tiktok.com/@trader_jan/video/123", "tiktok")
    assert post.author_handle == "@trader_jan"
    assert {"reklama", "forex"} <= {h.lower() for h in post.hashtags}
    assert post.mentions == ["@broker_pl"]
    assert post.external_links == ["https://broker.example/ref?c=1"]
    assert {"opengraph", "url-path"} <= set(post.extraction_sources)


@pytest.mark.parametrize(
    ("url", "platform", "expected"),
    [
        ("https://www.instagram.com/finanse_na_luzie/", "instagram", "@finanse_na_luzie"),
        ("https://www.instagram.com/p/C0abc123/", "instagram", None),
        ("https://www.youtube.com/@kanal_inwest", "youtube", "@kanal_inwest"),
        ("https://www.facebook.com/groups/123", "facebook", None),
        ("https://x.com/trader_pl/status/1", "x", "@trader_pl"),
    ],
)
def test_handle_from_url(url: str, platform: str, expected: str | None) -> None:
    assert handle_from_url(url, platform) == expected


# --- Proxy rotation -----------------------------------------------------------------


def test_proxy_rotation_picks_from_configured_pool(tmp_path: Path) -> None:
    pool = ["http://proxy-a:3128", "http://proxy-b:3128"]
    fetcher = PageFetcher(_settings(tmp_path, crawler_proxies=" , ".join(pool)))
    picked = {fetcher.pick_proxy() for _ in range(200)}
    assert picked == set(pool)
    assert PageFetcher(_settings(tmp_path)).pick_proxy() is None


def test_fetch_public_url_passes_rotated_proxy_and_user_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><p>ok</p></html>")

    real_client = httpx.AsyncClient

    class RecordingClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: object) -> None:
            seen["proxy"] = kwargs.pop("proxy", None)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", RecordingClient)
    monkeypatch.setattr(fetcher_module, "validate_public_url", lambda u: u)

    fetcher = PageFetcher(_settings(tmp_path, crawler_proxies="http://proxy-a:3128", crawler_rate_limit_seconds=0))
    page = asyncio.run(fetcher.fetch_public_url("https://example.org/a"))
    assert page.status_code == 200
    assert seen["proxy"] == "http://proxy-a:3128"
    assert seen["ua"] in fetcher_module.ETHICAL_USER_AGENTS


# --- Persistent queue ---------------------------------------------------------------


def test_persistent_queue_claim_requeue_and_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    # Legacy schema (pre-1.2.0) without request_json / embedding_json columns
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE crawl_jobs (job_id TEXT PRIMARY KEY, mode TEXT NOT NULL, target TEXT,
                status TEXT NOT NULL, processed_count INTEGER NOT NULL DEFAULT 0,
                incidents_created INTEGER NOT NULL DEFAULT 0, error_message TEXT,
                created_at TEXT NOT NULL, finished_at TEXT);
            CREATE TABLE content_snapshots (content_hash TEXT PRIMARY KEY, source_url TEXT NOT NULL,
                source_platform TEXT NOT NULL, storage_key TEXT NOT NULL,
                vector_dim INTEGER NOT NULL DEFAULT 0, fetched_at TEXT NOT NULL);
            """
        )
    db = Database(db_path, tmp_path / "store")
    db.init_schema()

    assert db.claim_next_crawl_job() is None
    db.create_crawl_job("job_a", "mock_all", "mock_all", request_json='{"mode":"mock_all"}')
    db.create_crawl_job("job_b", "mock_all", "mock_all", request_json='{"mode":"mock_all"}')

    assert db.claim_next_crawl_job() == ("job_a", '{"mode":"mock_all"}')
    # Simulated crash: job_a stays 'running' -> re-queued on next start
    assert db.requeue_interrupted_crawl_jobs() == 1
    claimed = {db.claim_next_crawl_job()[0], db.claim_next_crawl_job()[0]}  # type: ignore[index]
    assert claimed == {"job_a", "job_b"}
    assert db.claim_next_crawl_job() is None


# --- Watchlist + scheduler + near-duplicate dedup ------------------------------------


def test_watchlist_crud_and_ssrf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import watchlist as watchlist_router

    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        blocked = client.post("/api/v1/watchlist", json={"url": "http://169.254.169.254/"})
        assert blocked.status_code == 400

        monkeypatch.setattr(watchlist_router, "validate_public_url", lambda u: u)
        created = client.post(
            "/api/v1/watchlist",
            json={"url": "https://www.tiktok.com/@trader_jan", "label": "TikTok", "module_ids": [1]},
        )
        assert created.status_code == 201
        target = created.json()
        assert target["module_ids"] == [1] and target["enabled"] is True

        dup = client.post("/api/v1/watchlist", json={"url": "https://www.tiktok.com/@trader_jan"})
        assert dup.status_code == 409

        listing = client.get("/api/v1/watchlist").json()
        assert [t["id"] for t in listing["items"]] == [target["id"]]
        assert listing["schedule"] == "disabled"

        disabled = client.patch(f"/api/v1/watchlist/{target['id']}", json={"enabled": False})
        assert disabled.json()["enabled"] is False

        assert client.delete(f"/api/v1/watchlist/{target['id']}").status_code == 204
        assert client.delete(f"/api/v1/watchlist/{target['id']}").status_code == 404


def test_watchlist_run_scans_target_and_merges_near_duplicate_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.routers import watchlist as watchlist_router

    url = "https://www.tiktok.com/@krypto_luksus_pl/video/1"
    base_html = (MOCK_DIR / "finfluencer_tiktok_cfd.html").read_text(encoding="utf-8")
    versions = iter(
        [
            base_html,
            base_html.replace("</body>", "<p>Wyświetlenia: 15 320.</p></body>"),
        ]
    )

    async def fake_fetch(target_url: str, use_playwright: bool = False) -> FetchedPage:
        return FetchedPage(
            source_url=target_url,
            final_url=target_url,
            source_platform="tiktok",
            raw_html=next(versions),
            status_code=200,
        )

    settings = _settings(tmp_path, crawler_schedule_include_mocks=False)
    with TestClient(create_app(custom_settings=settings)) as client:
        monkeypatch.setattr(watchlist_router, "validate_public_url", lambda u: u)
        monkeypatch.setattr(client.app.state.fetcher, "fetch_public_url", fake_fetch)
        client.post("/api/v1/watchlist", json={"url": url, "module_ids": [1]})

        totals = []
        for _ in range(2):
            run = client.post("/api/v1/watchlist/run")
            assert run.status_code == 202
            job_ids = run.json()["job_ids"]
            assert len(job_ids) == 1
            assert _wait_for_job(client, job_ids[0])["status"] == "completed"
            found = client.get("/api/v1/incidents", params={"module_id": 1, "search": "krypto_luksus_pl/video"}).json()
            totals.append(found["total"])

        assert totals == [1, 1], "Zmieniony licznik wyświetleń nie powinien tworzyć nowego incydentu"
        inc = client.get("/api/v1/incidents", params={"module_id": 1, "search": "krypto_luksus_pl/video"}).json()["items"][0]
        assert inc["source_url"] == url
        assert inc["promoter_name"] == "@krypto_luksus_pl"
        assert client.get("/api/v1/watchlist").json()["items"][0]["last_enqueued_at"]


def test_cron_schedule_is_reported(tmp_path: Path) -> None:
    settings = _settings(tmp_path, crawler_enable_scheduler=True, crawler_cron="*/30 * * * *")
    with TestClient(create_app(custom_settings=settings)) as client:
        data = client.get("/api/v1/watchlist").json()
        assert data["schedule"] == "cron: */30 * * * * (UTC)"
        assert data["scheduler_next_run"]
        assert client.get("/api/v1/health").json()["scheduler_running"] is True


# --- Filters and reports ------------------------------------------------------------


def test_risk_level_filter(tmp_path: Path) -> None:
    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        everything = client.get("/api/v1/incidents?limit=500").json()
        high = client.get("/api/v1/incidents?risk_level=high&limit=500").json()
        assert 0 < high["total"] < everything["total"]
        assert all(i["risk_level"] == "high" for i in high["items"])
        assert client.get("/api/v1/incidents?risk_level=critical").status_code == 422


def test_module_reports_json_and_csv_with_formula_escaping(tmp_path: Path) -> None:
    with TestClient(create_app(custom_settings=_settings(tmp_path))) as client:
        created = client.post(
            "/api/v1/analyze/text",
            json={
                "title": '=HYPERLINK("http://evil.example","klik")',
                "content": (
                    "XTradePro — handluj kontraktami CFD z dźwignią 1:500! Zero ryzyka, "
                    "gwarantowany zysk 40% miesięcznie. Otwórz konto w 5 minut."
                ),
            },
        ).json()["items"][0]
        module_id = created["module_id"]

        report = client.get(f"/api/v1/reports/{module_id}").json()
        listed = client.get(f"/api/v1/incidents?module_id={module_id}&limit=500").json()
        assert report["total"] == listed["total"]
        assert {"entity_name", "promoter_name", "source_url", "content_excerpt"} <= set(report["items"][0])

        resp = client.get(f"/api/v1/reports/{module_id}?format=csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.text.startswith("﻿")
        rows = list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))
        assert rows[0][0] == "id" and len(rows) == report["total"] + 1
        titles = [r[rows[0].index("title")] for r in rows[1:]]
        assert any(t.startswith("'=HYPERLINK") for t in titles)
        assert not any(t.startswith("=") for t in titles)

        assert client.get("/api/v1/reports/4").status_code == 422
