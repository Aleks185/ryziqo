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


CFD_AD_WITHOUT_WARNING = (
    "XTradePro — handluj kontraktami CFD na złoto i ropę z dźwignią 1:500! "
    "Zero ryzyka, gwarantowany zysk 40% miesięcznie. Otwórz konto w 5 minut i zacznij zarabiać już dziś."
)


def test_analyze_text_returns_contract_incident_and_dedupes(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        body = {
            "content": CFD_AD_WITHOUT_WARNING,
            "title": "Test CFD",
            "source_url": "manual://sample/T1",
            "module_ids": [1, 2, 3],
            "ground_truth_label": True,
        }
        resp = client.post("/api/v1/analyze/text", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] in ("live", "demo_fallback")
        assert len(data["items"]) >= 1
        inc = data["items"][0]
        assert inc["module_id"] in (1, 2, 3)
        assert inc["source_platform"] == "manual"
        assert inc["source_url"] == "manual://sample/T1"
        assert inc["ground_truth_label"] is True
        assert 0.0 <= inc["risk_score"] <= 1.0
        assert inc["raw_text_preview"]

        # Analyst decision survives re-analysis of identical content (dedup by content_hash)
        client.patch(f"/api/v1/incidents/{inc['id']}/status", json={"status": "in_review"})
        again = client.post("/api/v1/analyze/text", json=body).json()["items"][0]
        assert again["id"] == inc["id"]
        assert again["status"] == "in_review"


def test_analyze_text_escapes_markup_and_validates_input(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        too_short = client.post("/api/v1/analyze/text", json={"content": "za krótko"})
        assert too_short.status_code == 422

        bad_module = client.post(
            "/api/v1/analyze/text", json={"content": CFD_AD_WITHOUT_WARNING, "module_ids": [4]}
        )
        assert bad_module.status_code == 422

        payload = "<script>alert(1)</script> " + CFD_AD_WITHOUT_WARNING
        resp = client.post("/api/v1/analyze/text", json={"content": payload})
        assert resp.status_code == 200
        preview = resp.json()["items"][0]["raw_text_preview"]
        assert "<script>" in preview  # pasted markup kept as literal text, not parsed as HTML


def test_analyze_url_rejects_ssrf_targets(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        for url in (
            "http://127.0.0.1:8000/api/v1/health",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ):
            resp = client.post("/api/v1/analyze/url", json={"url": url})
            assert resp.status_code == 400, url


def test_label_patch_updates_calibration(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        inc_id = client.get("/api/v1/incidents").json()["items"][0]["id"]

        resp = client.patch(f"/api/v1/incidents/{inc_id}/label", json={"ground_truth_label": False})
        assert resp.status_code == 200
        assert resp.json()["ground_truth_label"] is False

        cleared = client.patch(f"/api/v1/incidents/{inc_id}/label", json={"ground_truth_label": None})
        assert cleared.json()["ground_truth_label"] is None

        missing = client.patch("/api/v1/incidents/nope/label", json={"ground_truth_label": True})
        assert missing.status_code == 404
