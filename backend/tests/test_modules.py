"""Unit tests for HTML preprocessing, DOM/CSS metrics, and analytical Modules 1-3."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.module1_finfluencers import analyze_module1
from app.ai.module2_risk_compliance import analyze_module2
from app.ai.module3_shadow_advisory import analyze_module3
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import cosine_similarity, preprocess_html
from app.config import Settings
from app.knf_registry import KNFRegistrySnapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _make_registry() -> KNFRegistrySnapshot:
    return KNFRegistrySnapshot(
        snapshot_path=DATA_DIR / "knf_registry_snapshot.json",
        rules_path=DATA_DIR / "risk_criteria_rules.json",
    )


def _offline_ollama() -> OllamaClient:
    client = OllamaClient(Settings(ollama_base_url="http://127.0.0.1:1"))
    client.is_available = False
    return client


@pytest.mark.anyio
async def test_module1_detects_undisclosed_finfluencer_promo() -> None:
    html = (DATA_DIR / "mock_sites" / "finfluencer_tiktok_cfd.html").read_text(encoding="utf-8")
    doc = preprocess_html(html, "mock://finfluencer_tiktok_cfd.html", "tiktok", is_mock_source=True)
    res = await analyze_module1(doc, _make_registry(), _offline_ollama())

    assert res.module_id == 1
    assert res.relevant is True
    assert res.risk_score >= 0.70
    assert res.knf_registry_status == "registered_eu_crossborder"
    assert any(r.rule_id == "M1_UNDISCLOSED_AD" for r in res.violated_rules)


@pytest.mark.anyio
async def test_module2_detects_dom_and_legal_violations() -> None:
    html = (DATA_DIR / "mock_sites" / "broker_promo_hidden_risk.html").read_text(encoding="utf-8")
    doc = preprocess_html(html, "mock://broker_promo_hidden_risk.html", "web", is_mock_source=True)
    res = await analyze_module2(doc, _make_registry(), _offline_ollama())

    assert res.module_id == 2
    assert res.risk_score >= 0.80
    rule_ids = {r.rule_id for r in res.violated_rules}
    assert {"3", "4", "5", "6", "7", "8", "10", "17", "18"}.issubset(rule_ids)
    assert doc.dom_metrics.risk_font_px == 8.0
    assert doc.dom_metrics.requires_click_to_view_risk is True
    assert doc.dom_metrics.low_contrast_detected is True


@pytest.mark.anyio
async def test_module2_passes_compliant_material() -> None:
    html = (DATA_DIR / "mock_sites" / "broker_promo_compliant.html").read_text(encoding="utf-8")
    doc = preprocess_html(html, "mock://broker_promo_compliant.html", "web", is_mock_source=True)
    res = await analyze_module2(doc, _make_registry(), _offline_ollama())

    assert res.risk_score < 0.30
    assert len(res.violated_rules) == 0


@pytest.mark.anyio
async def test_module3_detects_shadow_advisory_and_ignores_tax_office() -> None:
    registry = _make_registry()
    ollama = _offline_ollama()

    bad_html = (DATA_DIR / "mock_sites" / "shadow_wealth_management.html").read_text(encoding="utf-8")
    bad_doc = preprocess_html(bad_html, "mock://shadow_wealth_management.html", "web", is_mock_source=True)
    bad_res = await analyze_module3(bad_doc, registry, ollama)
    assert bad_res.risk_score >= 0.75
    assert any(r.rule_id == "M3_ART76_PERSONAL_REC" for r in bad_res.violated_rules)

    ok_html = (DATA_DIR / "mock_sites" / "shadow_general_education.html").read_text(encoding="utf-8")
    ok_doc = preprocess_html(ok_html, "mock://shadow_general_education.html", "web", is_mock_source=True)
    ok_res = await analyze_module3(ok_doc, registry, ollama)
    assert ok_res.risk_score < 0.30
    assert len(ok_res.violated_rules) == 0


def test_embedding_similarity_is_deterministic() -> None:
    doc1 = preprocess_html("<p>Kontrakty CFD i wysokie ryzyko utraty kapitału.</p>", "mock://a.html", "web")
    doc2 = preprocess_html("<p>Kontrakty CFD i wysokie ryzyko utraty kapitału.</p>", "mock://b.html", "web")
    assert cosine_similarity(doc1.embedding, doc2.embedding) == pytest.approx(1.0, abs=1e-3)
