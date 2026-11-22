"""Differentiators P1, P2, P4, P6: visible AI safeguards, citizen consent, evidence pack, relationship graph."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import time
import zipfile
from dataclasses import replace
from pathlib import Path

from PIL import Image

from app import ocr
from app.evidence import detect_warning_change, timestamp_request, timestamp_status
from app.threat_intel import mask_personal_data
from tests.test_api import DATA_DIR, _build_test_client

API = "/api/v1"
PROFIT = "<p>Zarabiaj do 20% rocznie na akcjach i funduszach ETF. Otwórz rachunek już dziś!</p>"
RISK_BOX = (
    '<div class="risk-box">Inwestowanie w instrumenty finansowe wiąże się z ryzykiem utraty części '
    "lub całości zainwestowanego kapitału.</div>"
)


def _crawl_mock(client, filename: str, module_ids=(1, 2, 3)) -> None:
    res = client.post(f"{API}/crawl/trigger", json={"mode": "mock_single", "mock_file": filename, "module_ids": list(module_ids)})
    assert res.status_code == 202
    deadline = time.time() + 30
    while time.time() < deadline:
        job = client.get(f"{API}/crawl/jobs").json()["jobs"][0]
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "completed", job


def _incident_for(client, source_url: str, module_id: int | None = None) -> dict:
    items = client.get(f"{API}/incidents?limit=500").json()["items"]
    found = [i for i in items if i["source_url"] == source_url and (module_id is None or i["module_id"] == module_id)]
    assert found, f"brak incydentu dla {source_url}"
    return client.get(f"{API}/incidents/{found[0]['id']}").json()


def _analyze_page(client, page):
    worker = client.app.state.worker
    return client.portal.call(lambda: worker.analyze_page(page, [2]))


# --- P1 -------------------------------------------------------------------------------------

def test_prompt_injection_mock_exposes_snippets_and_quote_checks(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        _crawl_mock(client, "broker_promo_prompt_injection.html", [2])
        detail = _incident_for(client, "mock://broker_promo_prompt_injection.html", 2)
        assert any(r["rule_id"] == "AI_PROMPT_INJECTION" for r in detail["violated_rules"])
        assert detail["prompt_injection_snippets"]
        assert any("risk_score" in s for s in detail["hidden_text_snippets"])
        # The hidden payload never reaches the analysed text
        assert "Zignoruj" not in (detail["raw_text_preview"] or "")
        assert len(detail["quote_checks"]) == len(detail["evidence_quotes"])
        assert {c["match"] for c in detail["quote_checks"]} <= {"exact", "fuzzy", "system"}


def test_similar_returns_confirmed_clone_and_stats_count_decisions(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        page = client.portal.call(client.app.state.worker.fetcher.fetch_mock_page, "broker_promo_hidden_risk.html")
        original = _analyze_page(client, page)[0]
        client.patch(f"{API}/incidents/{original.id}/status", json={"status": "confirmed"})
        items = client.get(f"{API}/incidents?limit=500").json()["items"]
        expected = sum(1 for i in items if i["ground_truth_label"] is not None or i["status"] in ("confirmed", "false_positive"))
        assert client.get(f"{API}/stats").json()["verified_decisions"] == expected > 0

        clone_page = replace(page, source_url="https://klon-nordic.example/oferta", final_url="https://klon-nordic.example/oferta",
                             is_mock_source=False)
        clone = _analyze_page(client, clone_page)[0]
        similar = client.get(f"{API}/incidents/{clone.id}/similar").json()
        match = next(s for s in similar if s["incident_id"] == original.id)
        assert match["label"] is True and match["status"] == "confirmed"
        assert match["is_clone"] is True and match["similarity"] >= 0.85


# --- P2 -------------------------------------------------------------------------------------

SCAM = "Zainwestuj 1000 zł i odbierz gwarantowane 9000 zł w tydzień! Mój PESEL 44051401359, karta 4111 1111 1111 1111."


def test_share_mode_none_stores_nothing(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        before = client.get(f"{API}/incidents?limit=500").json()["total"]
        res = client.post(f"{API}/analyze/text", json={"content": SCAM, "source_channel": "public_form", "share_mode": "none"})
        assert res.status_code == 200
        assert res.json()["items"] and res.json()["report"]["risk_score"] > 0
        assert client.get(f"{API}/incidents?limit=500").json()["total"] == before
        assert client.get(f"{API}/intelligence/reports", params={"q": "9000"}).json()["total"] == 0


def test_anonymous_and_signed_reports(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        anon = client.post(f"{API}/analyze/text", json={"content": SCAM, "source_channel": "public_form", "share_mode": "anonymous"}).json()
        key = "0f8c2b9e-5d1a-4c3e-9b7a-123456789abc"
        signed = client.post(f"{API}/analyze/text", json={
            "content": SCAM + " Drugi raz.", "source_channel": "public_form", "share_mode": "signed",
            "reporter_display_name": "  Czujny   Obywatel ", "reporter_key": key,
        }).json()
        with client.app.state.intel.connection() as c:
            rows = {r["id"]: dict(r) for r in c.execute("SELECT * FROM threat_reports")}
        a, s = rows[anon["report"]["report_id"]], rows[signed["report"]["report_id"]]
        assert a["reporter_ip"] is None and a["reporter_ip_hash"] is None and a["reporter_user_agent"] is None
        assert a["reporter_display_name"] is None and a["reporter_key_hash"] is None
        assert s["reporter_display_name"] == "Czujny Obywatel" and s["reporter_key_hash"] not in (None, key)
        assert "44051401359" not in a["excerpt"] and "[PESEL]" in a["excerpt"] and "[NUMER KARTY]" in a["excerpt"]
        public = client.get(f"{API}/intelligence/reports/{s['id']}").json()
        assert public["reporter_display_name"] == "Czujny Obywatel" and "reporter_key_hash" not in public


def test_signed_requires_identity(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        res = client.post(f"{API}/analyze/text", json={"content": SCAM, "share_mode": "signed"})
        assert res.status_code == 422


def test_mask_personal_data_keeps_amounts_and_invalid_numbers() -> None:
    text = "Wpłać 12345678901 zł? PESEL 44051401359, telefon 600 700 800, karta 4111-1111-1111-1111, konto 1234 5678 9012 3456"
    masked = mask_personal_data(text)
    assert "12345678901" in masked  # checksum-invalid: not a PESEL
    assert "[PESEL]" in masked and "600 700 800" in masked
    assert "[NUMER KARTY]" in masked and "1234 5678 9012 3456" in masked


def test_screenshot_uses_local_ocr_when_vlm_is_down(tmp_path: Path, monkeypatch) -> None:
    img = Image.new("RGB", (320, 120), "white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    body = {"image_base64": base64.b64encode(buf.getvalue()).decode(), "source_channel": "public_form", "share_mode": "anonymous"}
    async def passthrough(encoded: str) -> str:  # normalizacja wymaga Chromium; test dotyczy fallbacku OCR
        return encoded

    monkeypatch.setattr("app.routers.analyze.normalize_screenshot", passthrough)
    with _build_test_client(tmp_path) as client:
        monkeypatch.setattr("app.routers.analyze.ocr_read_text", lambda _: None)
        assert client.post(f"{API}/analyze/text", json=body).status_code == 503
        monkeypatch.setattr("app.routers.analyze.ocr_read_text",
                            lambda _: "Zainwestuj 500 zł i zarabiaj 3000 zł dziennie! Gwarantowany zysk bez ryzyka.")
        res = client.post(f"{API}/analyze/text", json=body)
        assert res.status_code == 200
        assert any("OCR" in item for item in res.json()["report"]["limitations"])


def test_ocr_lines_are_grouped_in_reading_order() -> None:
    result = [
        [[[200, 10], [300, 10], [300, 30], [200, 30]], "świat", 0.9],
        [[[10, 12], [150, 12], [150, 30], [10, 30]], "Witaj", 0.95],
        [[[10, 60], [150, 60], [150, 80], [10, 80]], "Druga linia", 0.8],
        [[[10, 90], [150, 90], [150, 99], [10, 99]], "szum", 0.1],
    ]
    assert ocr.lines_from_result(result) == ["Witaj świat", "Druga linia"]


# --- P4 -------------------------------------------------------------------------------------

def _page_html(body: str) -> str:
    return f"<html><head><title>Vistula ETF</title></head><body><main>{body}</main></body></html>"


def test_vanishing_risk_warning_is_flagged(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        base = client.portal.call(client.app.state.worker.fetcher.fetch_mock_page, "broker_promo_compliant.html")
        v1 = replace(base, source_url="mock://vanish.html", final_url="mock://vanish.html", raw_html=_page_html(PROFIT + RISK_BOX))
        first = _analyze_page(client, v1)
        assert not any(r.rule_id == "RISK_WARNING_REMOVED" for i in first for r in i.violated_rules)
        v2 = replace(v1, raw_html=_page_html(PROFIT))
        second = _analyze_page(client, v2)
        flagged = [i for i in second if any(r.rule_id == "RISK_WARNING_REMOVED" for r in i.violated_rules)]
        assert flagged and flagged[0].risk_score >= 0.75

        history = client.get(f"{API}/incidents/{flagged[0].id}/versions").json()
        assert [v["has_risk_warning"] for v in history["versions"]] == [True, False]
        assert history["last_change"]["warning_change"] == "removed"
        assert any("ryzykiem" in line for line in history["last_change"]["removed"])


def test_warning_shrink_detection() -> None:
    old = {"normalized_text": "Możesz stracić kapitał.", "dom_metrics": {"risk_font_px": 16}, "fetched_at": "a"}
    small = {**old, "dom_metrics": {"risk_font_px": 9}, "fetched_at": "b"}
    assert detect_warning_change(old, small).kind == "shrunk"
    assert detect_warning_change(old, {**old, "dom_metrics": {"risk_font_px": 15}}) is None


def test_evidence_pack_manifest_matches_files(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        _crawl_mock(client, "broker_promo_hidden_risk.html", [2])
        detail = _incident_for(client, "mock://broker_promo_hidden_risk.html", 2)
        res = client.get(f"{API}/incidents/{detail['id']}/evidence-pack")
        assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
        assert "evidence_pack_" in res.headers["content-disposition"]
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        names = set(zf.namelist())
        assert {"source.html", "extraction.json", "incident.json", "versions.json", "manifest.json", "manifest.sha256"} <= names
        manifest_bytes = zf.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        for entry in manifest["files"]:
            assert hashlib.sha256(zf.read(entry["path"])).hexdigest() == entry["sha256"]
        assert zf.read("manifest.sha256").decode().split()[0] == hashlib.sha256(manifest_bytes).hexdigest()
        assert client.get(f"{API}/incidents/nie-ma/evidence-pack").status_code == 404


def test_rfc3161_request_encoding() -> None:
    digest = hashlib.sha256(b"manifest").digest()
    req = timestamp_request(digest, nonce=12345)
    assert req[0] == 0x30 and digest in req and req.endswith(b"\x01\x01\xff")
    # TimeStampResp { PKIStatusInfo { status 0 } } and a rejection (status 2)
    assert timestamp_status(bytes.fromhex("3005300302010" + "0")) == 0
    assert timestamp_status(bytes.fromhex("30053003020102")) == 2
    assert timestamp_status(b"\x04\x00") is None


# --- P6 -------------------------------------------------------------------------------------

def test_graph_links_clone_and_shared_entities(tmp_path: Path) -> None:
    with _build_test_client(tmp_path) as client:
        page = client.portal.call(client.app.state.worker.fetcher.fetch_mock_page, "broker_promo_hidden_risk.html")
        original = _analyze_page(client, page)[0]
        client.patch(f"{API}/incidents/{original.id}/status", json={"status": "confirmed"})
        html = page.raw_html.replace("</main>", '<a href="https://partner.example/start?ref=ABC123">Dołącz</a></main>')
        for host in ("klon-a.example", "klon-b.example"):
            url = f"https://{host}/oferta"
            _analyze_page(client, replace(page, source_url=url, final_url=url, raw_html=html, is_mock_source=False))
        graph = client.get(f"{API}/intelligence/graph", params={"min_score": 0.3}).json()
        nodes = {n["id"]: n for n in graph["nodes"]}
        assert f"incident:{original.id}" in nodes
        types = {e["type"] for e in graph["edges"]}
        assert "clone_of" in types
        assert "referral_code:ref=abc123" in nodes and "link_domain:partner.example" in nodes
        assert all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"])
