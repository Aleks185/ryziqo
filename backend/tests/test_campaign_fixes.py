"""Regression tests for the campaign-logic review (docs/kampanie-fejkow.md, K1–K3, W1–W5, S1–S5, N1–N3)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.ai.aggregator import apply_clone_matches, select_results
from app.ai.module1_finfluencers import ModuleAnalysisResult
from app.ai.retrieval import CloneMatch, Retriever, best_similarity, clone_rule, source_domain
from app.database import Database
from app.models import Incident, ViolatedRule
from app.routers import crawl as crawl_router
from app.scraper.fetcher import FetchedPage
from app.threat_intel import Intelligence, domain_of, enrich_page, input_meta, normalized
from app.models import AnalyzeTextRequest
from app.verdicts import verdict_for_status
from tests.test_ai_detection import PARAPHRASE_POST, FakeVectorSource, _doc, _row
from tests.test_api import _build_test_client

API = "/api/v1"
SCAM = "Wpłać 950 PLN i odbierz gwarantowane 9000 PLN w 7 dni! Zysk bez ryzyka, tylko dziś."
NO_DB = SimpleNamespace(hosting_asn_db="", hosting_country_db="")


def _text(client, content, **extra):
    body = {"content": content, "module_ids": [2], "source_channel": "analyst_panel", **extra}
    res = client.post(API + "/analyze/text", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _report(client, report_id):
    return client.get(f"{API}/intelligence/reports/{report_id}").json()


def _confirm(client, report_id, verdict="confirmed_fake"):
    res = client.patch(f"{API}/intelligence/reports/{report_id}", json={"verdict_status": verdict})
    assert res.status_code == 200, res.text


def _wait_for_job(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for job in client.get(API + "/crawl/jobs").json()["jobs"]:
            if job["job_id"] == job_id and job["status"] in ("completed", "failed"):
                return job
        time.sleep(0.2)
    raise AssertionError("crawl job did not finish")


# --- K1 -------------------------------------------------------------------------------------------
def test_k1_public_url_crawl_feeds_registry_and_fast_path(tmp_path, monkeypatch):
    url = "https://scam-landing.example/promo"
    html = f"<html><head><title>Promo</title></head><body><p>{SCAM}</p></body></html>"

    async def fake_fetch(target_url, use_playwright=False):
        return FetchedPage(source_url=target_url, final_url=target_url, source_platform="web", raw_html=html,
                           status_code=200, redirect_chain=[target_url], target_server_ip="203.0.113.7")

    with _build_test_client(tmp_path) as client:
        monkeypatch.setattr(crawl_router, "validate_public_url", lambda u: u)
        monkeypatch.setattr(client.app.state.fetcher, "fetch_public_url", fake_fetch)
        job = client.post(API + "/crawl/trigger", json={"mode": "public_url", "target_url": url, "module_ids": [2]})
        assert job.status_code == 202
        assert _wait_for_job(client, job.json()["job_id"])["status"] == "completed"

        rows = client.get(API + "/intelligence/reports", params={"q": "scam-landing.example"}).json()["items"]
        assert len(rows) == 1 and rows[0]["origin"] == "crawler"
        detail = _report(client, rows[0]["id"])
        assert detail["target_server_ip"] == "203.0.113.7" and detail["redirect_chain"] == [url]

        incident = rows[0]["incident_ids"][0]
        assert client.patch(f"{API}/incidents/{incident}/status", json={"status": "confirmed"}).status_code == 200
        assert _report(client, rows[0]["id"])["verdict_status"] == "confirmed_fake"

        hit = client.post(API + "/analyze/url", json={"url": url + "?utm_source=fb", "module_ids": [2]}).json()
        assert hit["report"]["result_origin"] == "fast_path"


# --- K2 -------------------------------------------------------------------------------------------
def test_k2_text_link_choice_and_domain_parsing():
    meta = input_meta(AnalyzeTextRequest(content="Zarejestrowano w https://knf.gov.pl — wejdź na https://scam.xyz/start."))
    assert meta["canonical_domain"] == "scam.xyz"
    assert domain_of("https://knf.gov.pl@evil.xyz/login") == "evil.xyz"
    assert domain_of("https://scam.xyz:8080/a") == "scam.xyz"
    assert domain_of("ftp://scam.xyz/a") == ""


def test_k2_shared_neutral_domains_do_not_merge_campaigns(tmp_path):
    with _build_test_client(tmp_path) as client:
        for pair in (("Komunikat https://www.knf.gov.pl/komunikat-1 o zasadach nadzoru rynku.",
                      "Inny tekst o kursach walut i https://www.knf.gov.pl/ostrzezenia dla klientów."),
                     ("Super okazja, kliknij https://bit.ly/abc123 i zarabiaj od dziś.",
                      "Przepis na sernik babci, szczegóły https://bit.ly/zzz999 w opisie.")):
            first, second = (_text(client, c)["report"]["report_id"] for c in pair)
            assert _report(client, first)["campaign_id"] != _report(client, second)["campaign_id"]

        a = _text(client, "Pierwsza reklama inwestycji https://scam-site.xyz/a gwarantowany zysk.")["report"]["report_id"]
        b = _text(client, "Zupełnie inna treść, ale ten sam scam https://scam-site.xyz/b dziś.")["report"]["report_id"]
        assert _report(client, a)["campaign_id"] == _report(client, b)["campaign_id"]


# --- K3 -------------------------------------------------------------------------------------------
def test_k3_campaign_verdict_reaches_incident_memory(tmp_path):
    with _build_test_client(tmp_path) as client:
        db = client.app.state.db
        report = _text(client, SCAM)
        incident = report["items"][0]["id"]
        group = _report(client, report["report"]["report_id"])["campaign_id"]
        assert client.patch(f"{API}/intelligence/campaigns/{group}", json={"verdict_status": "confirmed_fake"}).status_code == 200
        inc = client.get(f"{API}/incidents/{incident}").json()
        assert inc["status"] == "confirmed" and inc["ground_truth_label"] is True
        assert any(r["id"] == incident and r["label"] is True for r in db.list_verified_incident_vectors())


def test_k3_incident_status_updates_every_report_and_overrides_label(tmp_path):
    with _build_test_client(tmp_path) as client:
        db = client.app.state.db
        first = _text(client, SCAM, ground_truth_label=True)
        second = _text(client, SCAM)  # cache hit: the same incident in a second report
        incident = first["items"][0]["id"]
        assert second["items"][0]["id"] == incident
        res = client.patch(f"{API}/incidents/{incident}/status", json={"status": "false_positive"})
        assert res.status_code == 200 and res.json()["ground_truth_label"] is False
        for r in (first, second):
            assert _report(client, r["report"]["report_id"])["verdict_status"] == "false_positive"
        assert not any(r["id"] == incident and r["label"] for r in db.list_verified_incident_vectors())


def test_k3_label_enables_fast_path_and_dismissed_mapping(tmp_path):
    assert verdict_for_status("dismissed") == "false_positive"
    with _build_test_client(tmp_path) as client:
        first = _text(client, SCAM)
        incident = first["items"][0]["id"]
        assert client.patch(f"{API}/incidents/{incident}/label", json={"ground_truth_label": True}).status_code == 200
        assert _report(client, first["report"]["report_id"])["verdict_status"] == "confirmed_fake"
        assert _text(client, SCAM)["report"]["result_origin"] == "fast_path"


def test_k3_status_wins_over_stale_label_in_clone_memory(tmp_path):
    db = Database(tmp_path / "t.db", tmp_path / "store")
    db.init_schema()
    doc = _doc(PARAPHRASE_POST, url="https://a.example/1")
    db.save_content_object(doc.content_hash, doc.source_url, "web", "<p>x</p>", doc.normalized_text,
                           embedding=doc.local_embedding, local_embedding=doc.local_embedding)
    now = "2026-11-21T00:00:00Z"
    db.upsert_incident(Incident(id="inc_1", module_id=1, module_name="M1", entity_name="X", source_url=doc.source_url,
                                title="t", content_excerpt="e", risk_score=0.9, risk_level="high", status="false_positive",
                                ground_truth_label=True, content_hash=doc.content_hash, detected_at=now, updated_at=now))
    assert [r["label"] for r in db.list_verified_incident_vectors()] == [False]


# --- W1 -------------------------------------------------------------------------------------------
def test_w1_tracking_params_and_redirects_are_canonicalized(tmp_path):
    with _build_test_client(tmp_path) as client:
        first = _text(client, "Reklama tygodnia https://www.facebook.com/ads/123?fbclid=AAA gwarantowany zysk 9000 PLN!")
        _confirm(client, first["report"]["report_id"])
        hit = _text(client, "Inna treść posta: https://www.facebook.com/ads/123/?utm_source=x&si=1")
        assert hit["report"]["result_origin"] == "fast_path"
        assert _report(client, hit["report"]["report_id"])["campaign_id"] == _report(client, first["report"]["report_id"])["campaign_id"]

    metas = []
    for short in ("https://bit.ly/a", "https://tinyurl.com/b"):
        meta = input_meta(SimpleNamespace(url=short, platform=None, content="", source_url=None))
        enrich_page(meta, FetchedPage(source_url=short, final_url="https://scam-landing.xyz/x?utm_campaign=1",
                                      source_platform="web", raw_html="<p>x</p>", status_code=200,
                                      redirect_chain=[short]), NO_DB)
        metas.append(meta)
    assert {m["canonical_domain"] for m in metas} == {"scam-landing.xyz"}
    assert metas[0]["redirect_chain"][0] == "https://bit.ly/a"
    assert metas[0]["platform"] == "Strona WWW"


# --- W2 -------------------------------------------------------------------------------------------
def test_w2_fast_path_points_at_full_analysis(tmp_path):
    with _build_test_client(tmp_path) as client:
        first = _text(client, SCAM)["report"]
        _confirm(client, first["report_id"])
        second = _text(client, SCAM, source_channel="public_form")["report"]
        group = _report(client, first["report_id"])["campaign_id"]
        client.patch(f"{API}/intelligence/campaigns/{group}", json={"verdict_status": "confirmed_fake"})
        third = _text(client, SCAM, source_channel="public_form")["report"]
        assert second["result_origin"] == third["result_origin"] == "fast_path"
        assert third["summary"].count("Dopasowano do potwierdzonego zagrożenia") == 1
        stored = _report(client, third["report_id"])
        assert stored["matched_id"] == first["report_id"]
        assert "Dopasowano" not in stored["ai_report_json"]["summary"]
        full = _report(client, first["report_id"])["duration"]
        assert stored["saved_seconds"] == pytest.approx(max(0, full - stored["duration"]), abs=1e-6)


# --- W3 / S2 / S1 ---------------------------------------------------------------------------------
def test_w3_pasted_texts_can_be_clones_and_rag_examples():
    original = _doc(PARAPHRASE_POST, url="manual://text")
    clone = _doc(PARAPHRASE_POST + " Link aktualny!", url="manual://text")
    retriever = Retriever(FakeVectorSource([_row(original, inc_id="inc_orig", url="manual://text", label=True)]),
                          rag_min_similarity=0.0)
    rag, clones = retriever.analyze(clone, [1])
    assert [c.incident_id for c in clones] == ["inc_orig"]
    assert rag[1][0].incident_id == "inc_orig"


def test_s2_subdomains_are_one_site():
    assert source_domain("https://promo.broker.pl/a") == source_domain("https://lp.broker.pl/b") == "broker.pl"
    assert source_domain("manual://text") == "" and source_domain(None) == ""


def test_s1_semantic_vector_decides_over_local_hash():
    local = [1.0] + [0.0] * 127
    semantic_a, semantic_b = [1.0] + [0.0] * 767, [0.0, 1.0] + [0.0] * 766
    assert best_similarity([semantic_a, local], [semantic_b, local]) == pytest.approx(0.0)
    assert best_similarity([semantic_a, local], [local]) == pytest.approx(1.0)  # fallback when only 128-dim is shared


# --- W4 -------------------------------------------------------------------------------------------
def test_w4_obfuscated_copy_hits_fast_path(tmp_path):
    assert normalized("Zysk 9000 PLN") == normalized("Zy​sk 9000 РLN")  # zero-width + Cyrillic Р
    with _build_test_client(tmp_path) as client:
        first = _text(client, SCAM)["report"]
        _confirm(client, first["report_id"])
        hit = _text(client, SCAM.replace("Wpłać", "W​płać").replace("PLN", "РLN"))["report"]
        assert hit["result_origin"] == "fast_path"


def test_w4_screenshot_text_links_with_pasted_text(tmp_path):
    from app.threat_intel import apply_read_text

    with _build_test_client(tmp_path) as client:
        intel = client.app.state.intel
        pasted = _text(client, SCAM)["report"]["report_id"]
        meta = {"source_type": "screenshot", "content_hash": "f" * 64, "image_phash": None, "canonical_domain": None,
                "target_url": None, "platform": "Inne", "excerpt": ""}
        apply_read_text(meta, SCAM)
        where, args = intel.relation(meta)
        with intel.connection() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM threat_reports WHERE " + where, args)]
        assert pasted in ids


# --- W5 / N2 --------------------------------------------------------------------------------------
def _result(module_id, score, rules=()):
    return ModuleAnalysisResult(module_id=module_id, module_name=f"M{module_id}", relevant=True, entity_name="E",
                                promoter_name=None, knf_registry_status="unknown", risk_score=score,
                                violated_rules=[ViolatedRule(rule_id=r, rule_name="r", legal_basis="b", reason="x") for r in rules])


def _clone(inc_id, sim=0.9):
    return CloneMatch(incident_id=inc_id, module_id=1, source_url="https://orig.example/", similarity=sim,
                      risk_score=0.9, title="t")


def test_w5_clone_never_lowers_score_and_survives_primary_selection():
    high = _result(1, 0.98, ["R1"])
    apply_clone_matches([high], [_clone("inc_a")])
    assert high.risk_score == 0.98

    m1, m2 = _result(1, 0.60, ["R1"]), _result(2, 0.85, ["R2"])
    apply_clone_matches([m1, m2], [_clone("inc_a"), _clone("inc_b", 0.88)])
    [primary] = select_results([m1, m2, _result(3, 0.1)], [1, 2, 3], "primary")
    assert primary is m2
    rule = next(r for r in primary.violated_rules if r.rule_id == "CAMPAIGN_CLONE_MATCH")
    assert rule.related_incident_ids == ["inc_a", "inc_b"]  # N2: every clone is kept
    assert sum(q.startswith("[Klon]") for q in primary.evidence_quotes) == 2


def test_n2_false_positives_do_not_push_confirmed_out(tmp_path):
    db = Database(tmp_path / "t.db", tmp_path / "store")
    db.init_schema()
    for n, status in enumerate(["confirmed", "false_positive", "false_positive", "false_positive"]):
        doc = _doc(PARAPHRASE_POST + f" wariant {n}", url=f"https://s{n}.example/")
        db.save_content_object(doc.content_hash, doc.source_url, "web", "<p>x</p>", doc.normalized_text,
                               embedding=doc.local_embedding, local_embedding=doc.local_embedding)
        stamp = f"2026-11-2{n}T00:00:00Z"
        db.upsert_incident(Incident(id=f"inc_{n}", module_id=1, module_name="M1", entity_name="X", source_url=doc.source_url,
                                    title="t", content_excerpt="e", risk_score=0.9, risk_level="high", status=status,
                                    content_hash=doc.content_hash, detected_at=stamp, updated_at=stamp))
    rows = db.list_verified_incident_vectors(limit=2)
    assert "inc_0" in {r["id"] for r in rows if r["label"]}


# --- S3 -------------------------------------------------------------------------------------------
def test_s3_newer_false_positive_and_module_coverage(tmp_path):
    with _build_test_client(tmp_path) as client:
        first = _text(client, SCAM)["report"]
        _confirm(client, first["report_id"])
        # the confirmed verdict covers module 2 only: a request for all modules gets a full analysis
        assert _text(client, SCAM, module_ids=[1, 2, 3])["report"]["result_origin"] != "fast_path"
        assert _text(client, SCAM)["report"]["result_origin"] == "fast_path"
        newer = _text(client, SCAM, force_full=True)["report"]
        _confirm(client, newer["report_id"], "false_positive")
        assert _text(client, SCAM)["report"]["result_origin"] != "fast_path"


def test_s3_count_skips_false_positives(tmp_path):
    with _build_test_client(tmp_path) as client:
        intel = client.app.state.intel
        first = _text(client, SCAM)["report"]
        second = _text(client, SCAM, force_full=True)["report"]
        _confirm(client, first["report_id"])
        meta = input_meta(AnalyzeTextRequest(content=SCAM))
        assert intel.confirmed(meta, [2])[1] == 2
        with intel.connection() as c:  # an older rejected duplicate is not "a previous report of the fake"
            c.execute("UPDATE threat_reports SET verdict_status='false_positive', created_at='2000-01-01T00:00:00Z' WHERE id=?",
                      (second["report_id"],))
        assert intel.confirmed(meta, [2])[1] == 1


# --- S4 -------------------------------------------------------------------------------------------
def test_s4_graph_uses_structured_clone_link_and_sql_filter(tmp_path):
    with _build_test_client(tmp_path) as client:
        db = client.app.state.db
        stamp = "2099-01-01T00:00:00Z"

        def incident(inc_id, score, status="new", rules=(), detected=stamp):
            db.upsert_incident(Incident(id=inc_id, module_id=1, module_name="M1", entity_name="X", source_url=f"https://{inc_id}.example/",
                                        title=inc_id, content_excerpt="e", risk_score=score, risk_level="high", status=status,
                                        violated_rules=list(rules), detected_at=detected, updated_at=detected))

        incident("orig", 0.4, "confirmed", detected="2020-01-01T00:00:00Z")  # below min_score, outside the window
        rule = clone_rule(_clone("orig")).model_copy(update={"reason": "Zmieniony opis reguły bez identyfikatora."})
        incident("copy", 0.9, rules=[rule], detected="2098-01-01T00:00:00Z")
        for n in range(3):
            incident(f"dismissed{n}", 0.9, "dismissed")  # newest rows, must not use up the limit
        graph = client.get(API + "/intelligence/graph", params={"limit": 1}).json()
        nodes = {n["id"] for n in graph["nodes"]}
        assert {"incident:copy", "incident:orig"} <= nodes
        assert not any(n.startswith("incident:dismissed") for n in nodes)
        assert {"source": "incident:copy", "target": "incident:orig", "type": "clone_of"} in graph["edges"]


# --- S5 -------------------------------------------------------------------------------------------
def test_s5_campaign_listing_notes_and_detach(tmp_path):
    with _build_test_client(tmp_path) as client:
        a = _text(client, "Reklama A https://scam-site.xyz/a gwarantowany zysk.")["report"]["report_id"]
        b = _text(client, "Reklama B https://scam-site.xyz/b gwarantowany zysk.")["report"]["report_id"]
        group = _report(client, a)["campaign_id"]
        assert client.patch(f"{API}/intelligence/campaigns/{group}", json={"analyst_notes": "Sprawdzone przez CERT"}).json()["updated"] == 2
        [campaign] = [c for c in client.get(API + "/intelligence/campaigns").json() if c["campaign_id"] == group]
        assert campaign["domain"] == "scam-site.xyz" and campaign["new_count"] == 2
        assert campaign["analyst_notes"] == "Sprawdzone przez CERT"

        client.patch(f"{API}/intelligence/campaigns/{group}", json={"verdict_status": "false_positive"})
        active = client.get(API + "/intelligence/campaigns", params={"active_only": True}).json()
        assert group not in {c["campaign_id"] for c in active}

        moved = client.post(f"{API}/intelligence/reports/{b}/detach").json()["campaign_id"]
        assert moved != group and _report(client, b)["campaign_id"] == moved
        c = _text(client, "Reklama C https://scam-site.xyz/c i jeszcze raz Reklama B https://scam-site.xyz/b")["report"]["report_id"]
        assert _report(client, b)["campaign_id"] == moved and _report(client, c)["campaign_id"] == group
        assert client.post(f"{API}/intelligence/reports/missing/detach").status_code == 404


# --- N1 / N3 --------------------------------------------------------------------------------------
def test_n1_phash_index_and_n3_short_text_hint(tmp_path):
    with _build_test_client(tmp_path) as client:
        intel = client.app.state.intel
        with intel.connection() as c:
            assert "threat_phash" in {r[1] for r in c.execute("PRAGMA index_list(threat_reports)")}
        _text(client, "Kup teraz tanio dziś")
        assert intel.context({"excerpt": "Kup teraz tanio dziś!", "content_hash": None}) == ""
        where, _ = Intelligence.relation({"image_phash": "00ff00ff00ff00ff"})
        assert "rowid IN" in where


# --- Leaderboard ----------------------------------------------------------------------------------
def test_leaderboard_one_point_per_fake_per_signed_reporter(tmp_path):
    def signed(name, key):
        return {"source_channel": "public_form", "share_mode": "signed", "reporter_display_name": name,
                "reporter_key": key * 20}

    with _build_test_client(tmp_path) as client:
        client.app.state.settings.report_limit_per_minute = 100
        for _ in range(3):  # the same fake three times: still one point
            first = _text(client, SCAM, **signed("Ala", "a"))
        _text(client, SCAM, **signed("Bartek", "b"))  # reported by someone else first: still a point
        _text(client, SCAM, source_channel="public_form", share_mode="anonymous")  # anonymous: no ranking
        group = _report(client, first["report"]["report_id"])["campaign_id"]
        client.patch(f"{API}/intelligence/campaigns/{group}", json={"verdict_status": "confirmed_fake"})
        board = client.get(API + "/intelligence/leaderboard").json()
        assert sorted((r["nickname"], r["points"]) for r in board) == [("Ala", 1), ("Bartek", 1)]

        other = _text(client, "Kup akcje spółki widmo z gwarancją 50% zysku miesięcznie, przelew na konto prywatne.",
                      **signed("Ala", "a"))
        _confirm(client, other["report"]["report_id"])
        board = {r["nickname"]: r["points"] for r in client.get(API + "/intelligence/leaderboard").json()}
        assert board == {"Ala": 2, "Bartek": 1}
