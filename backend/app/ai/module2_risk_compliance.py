"""Moduł 2: Weryfikacja zgodności i informacji o ryzyku (18 kryteriów UKNF / MiFID II / rozp. 2017/565)."""

from __future__ import annotations

import re

from app.ai.module1_finfluencers import ModuleAnalysisResult
from app.ai.solicitation import solicitation_signals
from app.ai.monetary_offer import assess_offer
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.knf_registry import KNFRegistrySnapshot
from app.models import ViolatedRule

PROFIT_CLAIM_RE = re.compile(
    r"(zarabiaj|zyskaj(?!\s+(?:ulgę|odliczenie|korzyść)\s+podatkow\w*)|pomnażaj|ponadprzeciętn\w*\s+zysk|zwrot\w*\s+[0-9]+%|"
    r"\+[0-9]+%|do\s+[0-9]+%\s+rocznie|bez\s+prowizji|szybki\s+zysk)",
    re.IGNORECASE,
)
PRODUCT_RE = re.compile(r"\b(?:ETF|CFD|fundusz\w*|akcj[ei]|obligacj[ei]|portfel\w* inwestycyjn\w*)\b", re.I)
INVITATION_RE = re.compile(r"\b(?:zainwestuj|zacznij inwestować|załóż (?:konto|rachunek)|otwórz rachunek|zautomatyzuj swoje inwestycje)\b", re.I)
BENEFIT_RE = re.compile(r"\b(?:doch[oó]d\w* pasywn\w*|optymaliz\w* wyniki|0\s*%\s*prowizji|niższe opłaty)\b", re.I)
PL_RISK_WARNING_RE = re.compile(
    r"(ryzyk\w*\s+utrat|utrat[aąey]\s+(?:części\s+lub\s+całości\s+)?(?:zainwestowanego\s+)?kapitał|"
    r"(?:inwestowanie|inwestycj\w*)\s+(?:wiąże|wiążą)\s+się\s+z\s+ryzykiem|"
    r"możesz\s+(?:stracić|utracić)\s+(?:część|całość|zainwestowan\w*|kapitał|pieniądze)|kontrakty\s+cfd\s+są\s+złożonymi\s+instrumentami)",
    re.IGNORECASE,
)
EN_RISK_ONLY_RE = re.compile(r"(risk\s+warning|capital\s+at\s+risk|cfds\s+are\s+complex)", re.IGNORECASE)
AD_LABEL_RE = re.compile(
    r"(informacja\s+reklamowa|materiał\s+reklamowy|materiał\s+promocyjny|"
    r"materiał\s+marketingowy|#reklama|reklama\b)",
    re.IGNORECASE,
)
COMPARISON_RE = re.compile(
    r"(niższe\s+opłaty\s+niż|najlepsz\w*\s+platform|średni[aą]\s+rynkow|nr\s*1\s+na\s+rynku|porównanie\s+z\s+rynkiem)",
    re.IGNORECASE,
)
COMPARISON_SOURCE_RE = re.compile(r"(źródło:|metodologi|na\s+podstawie\s+danych\s+z\s+dnia)", re.IGNORECASE)
HIST_PERF_RE = re.compile(
    r"(wypracował\s*\+?[0-9]+%|zarobił\s*\+?[0-9]+%|\+[0-9]+%\s+w\s+ostatni|wyniki\s+historyczne)",
    re.IGNORECASE,
)
FIVE_YEAR_RE = re.compile(r"(5\s+(?:pełnych\s+)?(?:lat|okresów\s+12-miesięcznych)|2021[–-]2025)", re.IGNORECASE)
HIST_DISCLAIMER_RE = re.compile(
    r"(wyniki\s+historyczne\s+.*nie\s+stanowią\s+wiarygodnego\s+wskaźnika\s+przyszłych)",
    re.IGNORECASE,
)
FX_FEE_RE = re.compile(r"(kursów\s+walutowych|wpływ\s+opłat|prowizji)", re.IGNORECASE)
FOREIGN_CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|CHF|amerykańskich)\b", re.IGNORECASE)
FORECAST_RE = re.compile(
    r"(prognozujemy|przewidujemy\s+[0-9]+%|oczekiwany\s+zwrot\s+[0-9]+%|prognoza\s+zwrotu)",
    re.IGNORECASE,
)
FORECAST_DISCLAIMER_RE = re.compile(
    r"(prognoz\w*\s+nie\s+(?:jest|stanowi)\s+wiarygodnym\s+wskaźnikiem)",
    re.IGNORECASE,
)
TAX_RE = re.compile(r"(podatk\w*\s+Belki|zero\s+podatku|bez\s+podatku|korzyści\s+podatkow|ulg[ęai]\s+podatkow\w*|odliczenie\s+podatkowe)", re.IGNORECASE)
TAX_DISCLAIMER_RE = re.compile(
    r"(zależ[ąy]\s+od\s+indywidualnej\s+sytuacji\s+klienta|mogą\s+ulec\s+zmianie)",
    re.IGNORECASE,
)
KNF_MENTION_RE = re.compile(r"\b(KNF|Komisj[aąi]\s+Nadzoru\s+Finansowego)\b", re.IGNORECASE)
KNF_SAFETY_ABUSE_RE = re.compile(
    r"(w\s+pełni\s+bezpieczn\w*.*KNF|KNF.*gwarantuje|spełniamy\s+rygorystyczne\s+wymogi.*KNF|"
    r"zatwierdzon\w*\s+przez\s+KNF|aprobata\s+KNF|bezpieczeństwo.*nadzor\w*\s+KNF)",
    re.IGNORECASE,
)

MODULE2_SYSTEM_PROMPT = """Jesteś ekspertem zgodności UKNF (Moduł 2 #InvestWatch — MiFID II art. 24 ust. 3 oraz rozp. del. 2017/565 art. 44).
Oceń proporcjonalność informacji o ryzyku względem przekazu o zyskach. Zwróć wyłącznie JSON:
{
  "risk_score": 0.0-1.0,
  "key_finding": "jedno zdanie podsumowania po polsku"
}"""


def _make_rule(rules_by_id: dict[str, dict], rule_id: str, severity: str, reason: str) -> ViolatedRule:
    meta = rules_by_id.get(rule_id, {})
    return ViolatedRule(
        rule_id=rule_id,
        rule_name=str(meta.get("name", f"Reguła UKNF {rule_id}")),
        legal_basis=str(meta.get("legal_basis", "rozporządzenie del. 2017/565")),
        severity=severity,  # type: ignore[arg-type]
        reason=reason,
    )


async def analyze_module2(
    doc: PreprocessedDocument,
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
) -> ModuleAnalysisResult:
    """Evaluate marketing material of an investment firm against the 18 UKNF risk criteria."""
    text = doc.normalized_text
    dom = doc.dom_metrics
    rules_by_id = registry.rules_by_id
    matched_entity = registry.match_entity_in_text(text)

    # Relevant when direct marketing from a registered PL/EU-branch investment firm (or explicit ad/CFD promo)
    is_registered_direct = (
        matched_entity is not None
        and matched_entity.registry_status in ("registered_pl", "registered_eu_branch")
        and doc.promoter_hint is None
    )
    has_profit_claim = bool(PROFIT_CLAIM_RE.search(text))
    relevant = is_registered_direct or (doc.promoter_hint is None and has_profit_claim)

    offer = assess_offer(text)
    relevant = relevant or bool(offer.quotes)
    violated: list[ViolatedRule] = []
    quotes = [q[:260] for q in offer.quotes]
    if offer.reason:
        violated.append(ViolatedRule(
            rule_id="M2_MONETARY_OFFER", rule_name="Obietnica zarobku w określonym czasie",
            legal_basis="Wskaźnik analityczny do weryfikacji",
            severity="high" if offer.floor >= 0.70 else "medium", reason=offer.reason,
        ))
    weighted_penalty = 0.0

    def add_violation(rule_id: str, severity: str, reason: str, quote_hint: str | None = None) -> None:
        nonlocal weighted_penalty
        violated.append(_make_rule(rules_by_id, rule_id, severity, reason))
        weight = float(rules_by_id.get(rule_id, {}).get("weight", 0.14))
        weighted_penalty += weight
        if quote_hint and quote_hint not in quotes:
            quotes.append(quote_hint[:260])

    # Rule 1: Firm identification
    if matched_entity is None and has_profit_claim:
        add_violation("1", "medium", "Brak jednoznacznej oficjalnej nazwy firmy inwestycyjnej w materiale.")

    # Rule 2: Ad labeling
    if has_profit_claim and not AD_LABEL_RE.search(text):
        add_violation("2", "medium", "Materiał promocyjny nie jest jednoznacznie oznaczony jako reklama.")

    # Rule 3: Profit claim paired with substantive Polish risk warning
    has_pl_risk = bool(PL_RISK_WARNING_RE.search(text))
    has_en_risk = bool(EN_RISK_ONLY_RE.search(text))
    promoted_benefit = bool(PRODUCT_RE.search(text) and INVITATION_RE.search(text) and BENEFIT_RE.search(text))
    missing_risk = (has_profit_claim or promoted_benefit) and not has_pl_risk
    if missing_risk:
        relevant = True
        matching_sent = next((s for s in doc.sentences if PROFIT_CLAIM_RE.search(s) or BENEFIT_RE.search(s)), doc.title)
        add_violation(
            "3",
            "high",
            "Materiał przedstawia korzyści inwestowania. W analizowanej treści nie znaleziono ostrzeżenia o ryzyku inwestycyjnym. Sprawdź pełną reklamę.",
            matching_sent,
        )

    # Rule 4: Font size ratio (DOM/CSS)
    if dom.font_ratio is not None and dom.font_ratio < 0.72:
        add_violation(
            "4",
            "high",
            f"Czcionka informacji o ryzyku ({dom.risk_font_px}px) stanowi jedynie {int(dom.font_ratio * 100)}% dominującej czcionki ({dom.dominant_font_px}px).",
            f"Metryka DOM: czcionka ryzyka {dom.risk_font_px}px vs dominująca {dom.dominant_font_px}px.",
        )

    # Rule 5: Exposure & contrast
    if dom.low_contrast_detected:
        add_violation(
            "5",
            "high",
            "Wykryto niski kontrast / niską czytelność elementu z informacją o ryzyku.",
            "Metryka DOM: kolor ostrzeżenia o zbyt niskim kontraście względem tła.",
        )

    # Rule 6: Risk hidden in footer / Legal
    if dom.risk_hidden_in_footer:
        add_violation(
            "6",
            "high",
            "Informacja o ryzyku została ukryta w stopce strony lub sekcji 'Legal'.",
        )

    # Rule 7: Hidden behind click (<details> / expandable layer)
    if dom.requires_click_to_view_risk:
        add_violation(
            "7",
            "medium",
            "Wyświetlenie informacji o ryzyku wymaga kliknięcia / rozwinięcia ukrytej sekcji.",
        )

    # Rule 8: Mobile responsiveness overflow
    if dom.responsive_overflow_detected:
        add_violation(
            "8",
            "medium",
            "Blok informacji o ryzyku przekracza szerokość ekranu mobilnego i ulega ucięciu.",
        )

    # Rule 10: Language consistency (Polish ad with English risk warning)
    if has_en_risk and not has_pl_risk:
        add_violation(
            "10",
            "high",
            "Główny przekaz jest w języku polskim, natomiast ostrzeżenie o ryzyku podano po angielsku.",
            "Wykryto anglojęzyczną klauzulę ryzyka ('Risk warning / Capital at risk') w polskojęzycznej reklamie.",
        )

    # Rule 11: Product comparisons without source
    if COMPARISON_RE.search(text) and not COMPARISON_SOURCE_RE.search(text):
        add_violation(
            "11",
            "medium",
            "Porównanie oferty z rynkiem bez wskazania źródła danych i przyjętych założeń.",
        )

    # Rules 12a, 12b, 14: Historical performance
    if HIST_PERF_RE.search(text):
        if not FIVE_YEAR_RE.search(text):
            sent = next((s for s in doc.sentences if HIST_PERF_RE.search(s)), None)
            add_violation(
                "12a",
                "high",
                "Wyniki historyczne nie obejmują wymaganych 5 pełnych okresów 12-miesięcznych ani źródła.",
                sent,
            )
        if FOREIGN_CURRENCY_RE.search(text) and not FX_FEE_RE.search(text):
            add_violation(
                "12b",
                "medium",
                "Prezentacja wyników w walucie obcej bez ostrzeżenia o ryzyku walutowym i wpływie opłat/prowizji.",
            )
        if not HIST_DISCLAIMER_RE.search(text):
            add_violation(
                "14",
                "high",
                "Brak wyraźnego zastrzeżenia, że wyniki historyczne nie stanowią wiarygodnego wskaźnika przyszłych wyników.",
            )

    # Rule 15: Future return forecasts
    if FORECAST_RE.search(text) and not FORECAST_DISCLAIMER_RE.search(text):
        sent = next((s for s in doc.sentences if FORECAST_RE.search(s)), None)
        add_violation(
            "15",
            "high",
            "Wykryto prognozę przyszłych wyników bez obowiązkowego ostrzeżenia o braku jej wiarygodności.",
            sent,
        )

    # Rule 16: Tax information
    missing_tax_terms = bool(TAX_RE.search(text) and not TAX_DISCLAIMER_RE.search(text))
    pension_tax_promotion = bool(
        missing_tax_terms and re.search(r"\b(?:IKE|IKZE)\b", text, re.I)
        and re.search(r"\b(?:wpłać|załóż|otwórz|zyskaj)\b", text, re.I)
    )
    relevant = relevant or pension_tax_promotion
    if missing_tax_terms:
        sent = next((s for s in doc.sentences if TAX_RE.search(s)), None)
        add_violation(
            "16",
            "medium",
            ("Sprawdź, którego konta dotyczy opisana korzyść podatkowa i na jakich warunkach przysługuje klientowi."
             if pension_tax_promotion else
             "Odwołanie do korzyści podatkowych bez informacji o zależności od indywidualnej sytuacji klienta i możliwości zmian prawa."),
            sent,
        )

    # Rules 17 & 18: KNF approval / safety abuse
    if KNF_SAFETY_ABUSE_RE.search(text):
        sent = next((s for s in doc.sentences if KNF_MENTION_RE.search(s)), None)
        add_violation(
            "17",
            "high",
            "Odwołanie do KNF sugerujące zatwierdzenie lub gwarancję oferowanego produktu.",
            sent,
        )
        add_violation(
            "18",
            "high",
            "Wykorzystanie nadzoru KNF jako argumentu rzekomego pełnego bezpieczeństwa inwestycji.",
            sent,
        )

    signals, passages, signal_floor = solicitation_signals(text)
    relevant = relevant or bool(signals)
    violated.extend(signals)
    quotes = list(dict.fromkeys([*(s[:260] for s in passages), *quotes]))

    # Map accumulated penalty smoothly into [0.10, 0.97]
    if not violated:
        score = 0.12
    else:
        score = round(min(0.97, 0.28 + weighted_penalty * 0.72), 4)

    if violated and not quotes and doc.sentences:
        quotes = [doc.sentences[0][:240]]

    model_used = "deterministic-uknf-18rules-fallback"
    is_fallback = True

    llm_data = await ollama.generate_json(
        MODULE2_SYSTEM_PROMPT,
        f"Podmiot: {matched_entity.official_name if matched_entity else 'nieznany'}\n"
        f"Wstępne naruszone reguły ({len(violated)}): {[v.rule_id for v in violated]}\n"
        f"Metryki DOM: {dom.model_dump()}\nTreść:\n{text[:2200]}",
    )
    if llm_data and isinstance(llm_data.get("risk_score"), (int, float)):
        llm_score = max(0.0, min(1.0, float(llm_data["risk_score"])))
        score = round(0.70 * score + 0.30 * llm_score, 4)
        model_used = f"{ollama.active_model} + uknf-18rules"
        is_fallback = False
        finding = llm_data.get("key_finding")
        if isinstance(finding, str) and finding.strip() and len(quotes) < 5:
            quotes.append(f"[AI] {finding.strip()[:220]}")

    return ModuleAnalysisResult(
        module_id=2,
        module_name="Weryfikacja zgodności i informacji o ryzyku",
        relevant=relevant,
        entity_name=matched_entity.official_name if matched_entity else doc.title[:90],
        promoter_name=None,
        knf_registry_status=matched_entity.registry_status if matched_entity else "unknown",
        risk_score=max(score, offer.floor, signal_floor, 0.40 if missing_risk or pension_tax_promotion else 0.0),
        evidence_quotes=quotes[:5],
        violated_rules=violated,
        model_used=model_used,
        is_demo_fallback=is_fallback,
    )
