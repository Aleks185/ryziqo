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


@pytest.mark.anyio
@pytest.mark.parametrize(("content", "minimum", "maximum", "quote"), [
    ("Nowy algorytm pozwala zarobić od 12 500 zł do nawet 45 000 zł w pierwszym tygodniu. "
     "Wystarczy wpłacić minimalny depozyt 950 PLN. Link zniknie o północy!", .70, 1, "45 000 zł"),
    ("Wpłać 950 PLN. Zarób 12,5 tys. zł w tydzień. Zostało tylko 17 wolnych miejsc!", .70, 1, "12,5 tys. zł"),
    ("Możesz zarobić 1 250,50 zł w ciągu 7 dni.", .40, .69, "1 250,50 zł"),
    ("Zdobądź za samo założenie konta aż 1 250,50 zł.", 0, .39, "1 250,50 zł"),
    ("Odbierz 200 PLN po rejestracji.", 0, .39, "200 PLN"),
    ("Uważaj na reklamy obiecujące: «Wpłać 950 zł. Zarób 12 500 zł w tydzień. Link zniknie o północy!»", 0, .39, None),
    ("Na webinar zostało tylko 17 wolnych miejsc. Udział kosztuje 200 zł.", 0, .39, None),
    ("Zysk nie jest gwarantowany. Minimalny depozyt 950 PLN.", 0, .39, None),
])
async def test_monetary_offer(content, minimum, maximum, quote):
    doc = preprocess_html(f"<p>{content}</p>", "manual://text", "manual")
    result = await analyze_module2(doc, _make_registry(), _offline_ollama())
    assert minimum <= result.risk_score <= maximum
    if quote:
        assert result.relevant
        assert any(quote in passage for passage in result.evidence_quotes)


@pytest.mark.anyio
@pytest.mark.parametrize("content", [
    "Rozpocznij naukę inwestowania od podstaw na bezpłatnym koncie demonstracyjnym.",
    "Rozpocznij naukę inwestowania od podstaw na bezpłatnym koncie demonstracyjnym. Poznaj działanie funduszy indeksowych ETF, zrozum ryzyko rynkowe i przetestuj swoje decyzje w bezpiecznym środowisku, zanim zainwestujesz realne środki.",
])
async def test_educational_demo_account(content):
    doc = preprocess_html(f"<p>{content}</p>", "manual://text", "manual")
    for analyze in (analyze_module1, analyze_module2, analyze_module3):
        result = await analyze(doc, _make_registry(), _offline_ollama())
        assert result.risk_score <= 0.12
        assert result.violated_rules == []
        assert result.evidence_quotes == []


@pytest.mark.anyio
async def test_education_with_personal_recommendation_still_flags():
    content = "Poznaj ETF na koncie demonstracyjnym. Przygotujemy spersonalizowane rekomendacje zakupu ETF."
    doc = preprocess_html(f"<p>{content}</p>", "manual://text", "manual")
    result = await analyze_module3(doc, _make_registry(), _offline_ollama())
    assert any(rule.rule_id == "M3_ART76_PERSONAL_REC" for rule in result.violated_rules)
    assert any("spersonalizowane" in quote for quote in result.evidence_quotes)


@pytest.mark.anyio
@pytest.mark.parametrize(("warning", "flagged"), [
    ("", True),
    ("Informacja o ryzyku: kliknij tutaj.", True),
    ("Inwestowanie wiąże się z ryzykiem utraty kapitału.", False),
    ("Możesz stracić część zainwestowanych środków.", False),
])
async def test_etf_promotion_requires_risk_information(warning, flagged):
    content = "Zautomatyzuj swoje inwestycje w fundusze ETF i zacznij budować dochód pasywny już od 500 zł miesięcznie! Nasze algorytmy automatycznie rebalansują Twój portfel 24/7, aby optymalizować wyniki w długim terminie. Załóż konto w 5 minut i odbierz 0% prowizji przez pierwsze 3 miesiące – oferta ważna tylko do końca tygodnia! " + warning
    doc = preprocess_html(f"<p>{content}</p>", "manual://text", "manual")
    result = await analyze_module2(doc, _make_registry(), _offline_ollama())
    assert any(r.rule_id == "3" for r in result.violated_rules) == flagged
    if flagged:
        assert result.relevant and result.risk_score >= .40
        assert any("dochód pasywny" in q for q in result.evidence_quotes)


@pytest.mark.anyio
async def test_pension_tax_offer_is_not_a_promised_return():
    content = "Zabezpiecz swoją przyszłość finansową dzięki kontu IKE oraz IKZE i zyskaj ulgę podatkową nawet do kilku tysięcy złotych rocznie zgodnie z obowiązującymi przepisami! Wpłać środki przed końcem roku kalendarzowego, aby nie stracić tegorocznego limitu. Sprawdź, ile możesz zaoszczędzić na podatku Belki!"
    async def evaluate(text):
        doc = preprocess_html(f"<p>{text}</p>", "manual://text", "manual")
        return await analyze_module2(doc, _make_registry(), _offline_ollama())

    result = await evaluate(content)
    assert result.relevant and .40 <= result.risk_score < .70
    assert [rule.rule_id for rule in result.violated_rules] == ["16"]
    assert any("ulgę podatkową" in q for q in result.evidence_quotes)
    mixed = await evaluate(content + " Zyskaj 300% w tydzień.")
    assert {"3", "16"}.issubset({r.rule_id for r in mixed.violated_rules})


@pytest.mark.anyio
async def test_module1_ignores_referral_codes_on_the_firms_own_site() -> None:
    html = "<html><body><h1>Kod polecający XTB</h1><p>Wpisz kod polecający przy zakładaniu konta.</p></body></html>"
    registry, ollama = _make_registry(), _offline_ollama()

    own = await analyze_module1(preprocess_html(html, "https://www.xtb.com/pl/kod", "web"), registry, ollama)
    assert not any(r.rule_id == "M1_UNDISCLOSED_AD" for r in own.violated_rules)

    third_party = await analyze_module1(preprocess_html(html, "https://bonusy-forex.pl/xtb", "web"), registry, ollama)
    assert any(r.rule_id == "M1_UNDISCLOSED_AD" for r in third_party.violated_rules)
