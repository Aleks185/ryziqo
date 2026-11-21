"""Moduł 1: Monitoring ekosystemu zewnętrznego (Finfluencerzy i podmioty trzecie)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.knf_registry import KNFRegistrySnapshot
from app.models import ViolatedRule

AFFILIATE_RE = re.compile(
    r"(link\s+w\s+bio|link\w*\s+partnersk|kod\s+polecaj|reflink|bonus\s+powitaln|"
    r"darmow[aąe]\s+akcj|grup[aąey]\s+sygnałow|zaproszeni|odbierz\s+dostęp\s+vip)",
    re.IGNORECASE,
)
AD_DISCLOSURE_RE = re.compile(
    r"(#reklama|#współpraca|#wspolpraca|materiał\s+sponsorowan|reklama\s+płatna|post\s+sponsorowany)",
    re.IGNORECASE,
)
HYPE_PROFIT_RE = re.compile(
    r"(szybki\s+zysk|pasywny\s+dochód|gwarantowan\w*\s+bonus|zero\s+prowizji|"
    r"zrobiłem\s+[0-9\s]+zł|dźwigni[aą]|forex|cfd|1:30|1:100|bez\s+ryzyka)",
    re.IGNORECASE,
)
RISK_WARN_RE = re.compile(
    r"(ryzyk\w*\s+utrat|możesz\s+stracić|złożonymi\s+instrumentami|wysokie\s+ryzyko\s+utraty)",
    re.IGNORECASE,
)
EDU_ONLY_RE = re.compile(
    r"(charakter\s+ogólnoedukacyjn|nie\s+promuje\s+żadnej\s+firmy|brak\s+linków\s+afiliacyjnych)",
    re.IGNORECASE,
)

MODULE1_SYSTEM_PROMPT = """Jesteś analitykiem UKNF oceniającym treści finfluencerów i podmiotów trzecich (Moduł 1 #InvestWatch).
Zwróć wyłącznie JSON:
{
  "risk_score": 0.0-1.0,
  "is_third_party_promo": true/false,
  "has_ad_disclosure": true/false,
  "summary_reason": "krótkie uzasadnienie po polsku"
}"""


@dataclass
class ModuleAnalysisResult:
    module_id: int
    module_name: str
    relevant: bool
    entity_name: str
    promoter_name: str | None
    knf_registry_status: str
    risk_score: float
    evidence_quotes: list[str] = field(default_factory=list)
    violated_rules: list[ViolatedRule] = field(default_factory=list)
    model_used: str = "deterministic-hybrid-fallback"
    is_demo_fallback: bool = True


def _extract_quotes(sentences: list[str], patterns: list[re.Pattern[str]], limit: int = 3) -> list[str]:
    quotes: list[str] = []
    for sent in sentences:
        if any(p.search(sent) for p in patterns):
            cleaned = sent[:260]
            if cleaned not in quotes:
                quotes.append(cleaned)
        if len(quotes) >= limit:
            break
    return quotes


async def analyze_module1(
    doc: PreprocessedDocument,
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
) -> ModuleAnalysisResult:
    """Detect third-party / finfluencer promotion of Polish and cross-border investment firms."""
    text = doc.normalized_text
    matched_entity = registry.match_entity_in_text(text)

    is_social = doc.source_platform in ("tiktok", "instagram", "facebook", "youtube")
    has_promoter = bool(doc.promoter_hint) or is_social
    has_affiliate = bool(AFFILIATE_RE.search(text))
    has_disclosure = bool(AD_DISCLOSURE_RE.search(text))
    has_hype = bool(HYPE_PROFIT_RE.search(text))
    has_risk_warn = bool(RISK_WARN_RE.search(text))
    is_edu_only = bool(EDU_ONLY_RE.search(text))

    relevant = has_promoter or has_affiliate or (
        matched_entity is not None and matched_entity.registry_status == "registered_eu_crossborder"
    )

    rules: list[ViolatedRule] = []
    score = 0.08

    if matched_entity and (has_promoter or has_affiliate):
        score += 0.25
        if matched_entity.registry_status == "registered_eu_crossborder":
            score += 0.14
            rules.append(
                ViolatedRule(
                    rule_id="M1_CROSSBORDER_PROMO",
                    rule_name="Polskojęzyczna promocja zagranicznej firmy inwestycyjnej",
                    legal_basis="Zakres Modułu 1 UKNF (działalność transgraniczna)",
                    severity="medium",
                    reason=f"Wykryto promocję zagranicznej firmy {matched_entity.official_name} przez podmiot trzeci.",
                )
            )

    if has_affiliate:
        score += 0.22
        if not has_disclosure:
            score += 0.20
            rules.append(
                ViolatedRule(
                    rule_id="M1_UNDISCLOSED_AD",
                    rule_name="Brak jednoznacznego oznaczenia współpracy reklamowej",
                    legal_basis="art. 24 ust. 3 MiFID II / praktyki finfluencerów",
                    severity="high",
                    reason="Treść zawiera linki partnerskie/kody polecające bez oznaczenia #reklama / #współpraca.",
                )
            )
        else:
            rules.append(
                ViolatedRule(
                    rule_id="M1_AFFILIATE_MONITORING",
                    rule_name="Współpraca afiliacyjna z firmą inwestycyjną",
                    legal_basis="Zakres Modułu 1 UKNF",
                    severity="medium",
                    reason="Zidentyfikowano oznaczoną współpracę reklamową — wymagany monitoring proporcjonalności przekazu.",
                )
            )

    if has_hype and not has_risk_warn and not is_edu_only:
        score += 0.22
        rules.append(
            ViolatedRule(
                rule_id="3",
                rule_name="Brak informacji o ryzyku przy obietnicy zysku",
                legal_basis="art. 44 ust. 2 lit. b rozporządzenia del. 2017/565",
                severity="high",
                reason="Promocja zysków/dźwigni bez równorzędnego ostrzeżenia o ryzyku utraty kapitału.",
            )
        )

    if is_edu_only and not has_affiliate and matched_entity is None:
        score = min(score, 0.15)
        rules.clear()

    score = round(max(0.0, min(1.0, score)), 4)
    quotes = _extract_quotes(doc.sentences, [AFFILIATE_RE, HYPE_PROFIT_RE])
    if rules and not quotes and doc.sentences:
        quotes = [doc.sentences[0][:240]]

    model_used = "deterministic-uknf-m1-fallback"
    is_fallback = True

    llm_data = await ollama.generate_json(
        MODULE1_SYSTEM_PROMPT,
        f"Platforma: {doc.source_platform}\nPromotor: {doc.promoter_hint or 'nieznany'}\n"
        f"Dopasowana firma KNF: {matched_entity.official_name if matched_entity else 'brak'}\n"
        f"Treść:\n{text[:2200]}",
    )
    if llm_data and isinstance(llm_data.get("risk_score"), (int, float)):
        llm_score = max(0.0, min(1.0, float(llm_data["risk_score"])))
        score = round(0.65 * score + 0.35 * llm_score, 4)
        model_used = f"{ollama.active_model} + uknf-m1-rules"
        is_fallback = False
        reason = llm_data.get("summary_reason")
        if isinstance(reason, str) and reason.strip() and len(quotes) < 4:
            quotes.append(f"[AI] {reason.strip()[:220]}")

    entity_name = (
        matched_entity.official_name
        if matched_entity
        else ("Brak reklamowanej firmy inwestycyjnej" if not has_affiliate else "Niezidentyfikowany podmiot promowany")
    )
    reg_status = matched_entity.registry_status if matched_entity else "unknown"

    return ModuleAnalysisResult(
        module_id=1,
        module_name="Monitoring ekosystemu zewnętrznego (Finfluencerzy)",
        relevant=relevant,
        entity_name=entity_name,
        promoter_name=doc.promoter_hint or (f"Konto {doc.source_platform}" if is_social else None),
        knf_registry_status=reg_status,
        risk_score=score,
        evidence_quotes=quotes,
        violated_rules=rules,
        model_used=model_used,
        is_demo_fallback=is_fallback,
    )
