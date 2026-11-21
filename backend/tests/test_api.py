"""Integration tests for FastAPI endpoints, calibration stats, crawler trigger, and /ws/alerts."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _build_test_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=str(DATA_DIR),
        database_path=str(tmp_path / "test_investwatch.db"),
        object_store_dir=str(tmp_path / "object_store"),
        ollama_base_url="http://127.0.0.1:1",
        crawler_enable_scheduler=False,
        watchlist_seed_on_start=False,
        crawler_per_host_delay_seconds=0,
    )
    app = create_app(custom_settings=settings)
    return TestClient(app)


def test_health_incidents_stats_and_status_patch(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        hdata = health.json()
        assert hdata["status"] == "ok"
        assert hdata["incidents_count"] >= 10

        inc_resp = client.get("/api/v1/incidents")
        assert inc_resp.status_code == 200
        payload = inc_resp.json()
        assert payload["total"] >= 10
        first_id = payload["items"][0]["id"]

        # Update status
        patch = client.patch(
            f"/api/v1/incidents/{first_id}/status",
            json={"status": "confirmed", "analyst_note": "Zweryfikowano w teście E2E."},
        )
        assert patch.status_code == 200
        assert patch.json()["status"] == "confirmed"

        # Threshold calibration shifts FP/FN
        stats_low = client.get("/api/v1/stats?threshold=0.20").json()
        stats_high = client.get("/api/v1/stats?threshold=0.90").json()
        assert stats_low["flagged_count"] > stats_high["flagged_count"]
        assert stats_low["calibration"]["fn"] <= stats_high["calibration"]["fn"]


def test_seed_sources_exist_as_mock_files() -> None:
    import json

    seed = json.loads((DATA_DIR / "demo_incidents_seed.json").read_text(encoding="utf-8"))
    for item in seed:
        fname = item["source_url"].removeprefix("mock://")
        assert (DATA_DIR / "mock_sites" / fname).exists(), f"Brak pliku mock dla seeda: {fname}"


def test_mock_all_crawl_does_not_duplicate_seed_or_reset_analyst_status(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        before = client.get("/api/v1/incidents?limit=500").json()
        target = before["items"][0]
        client.patch(
            f"/api/v1/incidents/{target['id']}/status",
            json={"status": "confirmed", "analyst_note": "nota analityka"},
        )

        for _ in range(2):  # powtórny skan również nie może dublować
            assert client.post("/api/v1/crawl/trigger", json={"mode": "mock_all"}).status_code == 202
            deadline = time.time() + 30.0
            while time.time() < deadline:
                job = client.get("/api/v1/crawl/jobs").json()["jobs"][0]
                if job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.2)
            assert job["status"] == "completed"

        after = client.get("/api/v1/incidents?limit=500").json()
        assert after["total"] == before["total"]
        kept = client.get(f"/api/v1/incidents/{target['id']}").json()
        assert kept["status"] == "confirmed"
        assert kept["analyst_note"] == "nota analityka"


def test_ssrf_rejected_on_crawl_trigger(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        resp = client.post(
            "/api/v1/crawl/trigger",
            json={"mode": "public_url", "target_url": "http://127.0.0.1:8000/api/v1/health"},
        )
        assert resp.status_code == 400


def test_websocket_receives_crawl_and_high_risk_alerts(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        with client.websocket_connect("/ws/alerts") as ws:
            welcome = ws.receive_json()
            assert welcome["type"] == "connected"

            trigger = client.post(
                "/api/v1/crawl/trigger",
                json={
                    "mode": "mock_single",
                    "mock_file": "broker_promo_hidden_risk.html",
                    "module_ids": [2],
                },
            )
            assert trigger.status_code == 202

            seen_types: set[str] = set()
            deadline = time.time() + 8.0
            while time.time() < deadline and "analysis_complete" not in seen_types:
                msg = ws.receive_json()
                seen_types.add(msg["type"])

            assert "crawler_status" in seen_types
            assert "high_risk_alert" in seen_types
            assert "analysis_complete" in seen_types
