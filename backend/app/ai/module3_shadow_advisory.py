"""Moduł 3: Identyfikacja usług nieautoryzowanych (Shadow Advisory — art. 76, art. 2 i 3 u.o.i.f.)."""

from __future__ import annotations

import re

from app.ai.context import AnalysisContext, request_llm_assessment
from app.ai.fusion import fuse_module_result, has_commercial_cta
from app.ai.module1_finfluencers import ModuleAnalysisResult
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.knf_registry import KNFRegistrySnapshot
from app.models import ViolatedRule

ADVISORY_ENTITY_RE = re.compile(
    r"(wealth\s+management|family\s+office|investment\s+consulting|doradztwo\s+inwestycyjn|"
    r"mentoring\s+finansow|zarządzanie\s+portfelem|private\s+wealth|konsultacje\s+1-na-1)",
    re.IGNORECASE,
)
PERSONALIZED_REC_RE = re.compile(
    r"(spersonalizowan\w*\s+rekomendacj|indywidualn\w*\s+(?:dobór|rekomendacj|doradztwo)|"
    r"na\s+podstawie\s+(?:analizy\s+)?Twojej\s+sytuacji|co\s+kupić.*(?:sprzedać|trzymać)|"
    r"które\s+(?:akcje|fundusze|obligacje)\s+(?:warto\s+)?(?:kupić|dokupić|sprzedać)|"
    r"wskażemy\s+dokładnie|success\s+fee|opłat[aąe]\s+sukcesow)",
    re.IGNORECASE,
)
FINANCIAL_INSTRUMENTS_RE = re.compile(
    r"\b(akcj[ieaą]|obligacj[ieaą]|etf|certyfikat\w*\s+inwestycyjn|opcj[ieaą]|"
    r"kontrakt\w*\s+terminow|kontrakt\w*\s+na\s+różnicę|cfd|papier\w*\s+wartościow|"
    r"instrument\w*\s+pochodn|tytuł\w*\s+uczestnictwa)\b",
    re.IGNORECASE,
)
EXPLICIT_NON_ADVISORY_RE = re.compile(
    r"(nie\s+świadczy\w*\s+usług\s+doradztwa\s+inwestycyjnego|"
    r"nie\s+przygotowuje\s+rekomendacji|rozliczani\w*\s+podatk|pit-38|biuro\s+rachunkowe|kancelaria\s+podatkowa)",
    re.IGNORECASE,
)
DISGUISED_EDU_RE = re.compile(r"(charakter\s+edukacyjny|tylko\s+edukacja)", re.IGNORECASE)

async def analyze_module3(
    doc: PreprocessedDocument,
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
    context: AnalysisContext | None = None,
) -> ModuleAnalysisResult:
    """Detect unauthorized investment advisory (art. 76 u.o.i.f.) offered by non-KNF entities."""
    text = doc.normalized_text
    matched_knf = registry.match_entity_in_text(text)

    has_advisory_profile = bool(ADVISORY_ENTITY_RE.search(text))
    has_personal_rec = bool(PERSONALIZED_REC_RE.search(text))
    instruments_found = list({m.group(0).lower() for m in FINANCIAL_INSTRUMENTS_RE.finditer(text)})
    has_non_advisory = bool(EXPLICIT_NON_ADVISORY_RE.search(text))
    has_disguised_edu = bool(DISGUISED_EDU_RE.search(text))

    # Relevant when entity is NOT in the local KNF snapshot and discusses advisory / wealth / tax-investment
    relevant = matched_knf is None and (
        has_advisory_profile or has_personal_rec or has_non_advisory
    )

    rules: list[ViolatedRule] = []
    quotes: list[str] = []
    score = 0.12

    if matched_knf is not None:
        # Authorized firm in local snapshot -> not shadow advisory
        return ModuleAnalysisResult(
            module_id=3,
            module_name="Identyfikacja usług nieautoryzowanych (Shadow Advisory)",
            relevant=False,
            entity_name=matched_knf.official_name,
            promoter_name=None,
            knf_registry_status=matched_knf.registry_status,
            risk_score=0.05,
            evidence_quotes=["Podmiot figuruje w lokalnym snapshocie rejestru firm inwestycyjnych KNF."],
            violated_rules=[],
            model_used="deterministic-uknf-m3-fallback",
            is_demo_fallback=True,
        )

    if has_non_advisory and not has_personal_rec:
        score = 0.16
        quotes = [
            next(
                (s[:240] for s in doc.sentences if EXPLICIT_NON_ADVISORY_RE.search(s)),
                "Wyraźne wyłączenie usług doradztwa inwestycyjnego (usługi podatkowe/księgowe).",
            )
        ]
    else:
        if has_advisory_profile:
            score += 0.28
        if has_personal_rec:
            score += 0.34
            sent = next((s for s in doc.sentences if PERSONALIZED_REC_RE.search(s)), None)
            if sent:
                quotes.append(sent[:260])
        if instruments_found:
            score += min(0.22, 0.08 * len(instruments_found))

        if has_personal_rec and instruments_found:
            rules.append(
                ViolatedRule(
                    rule_id="M3_ART76_PERSONAL_REC",
                    rule_name="Podejrzenie nieautoryzowanego doradztwa inwestycyjnego",
                    legal_basis="art. 76 oraz art. 2 i 3 ustawy o obrocie instrumentami finansowymi",
                    severity="high",
                    reason=(
                        "Oferta zawiera przesłanki indywidualnej rekomendacji nabycia/zbycia/trzymania "
                        f"instrumentów finansowych ({', '.join(instruments_found[:5])}) przez podmiot spoza snapshotu KNF."
                    ),
                )
            )
        elif has_advisory_profile and instruments_found:
            rules.append(
                ViolatedRule(
                    rule_id="M3_UNLICENSED_WEALTH_PROFILE",
                    rule_name="Podmiot wealth/consulting oferujący usługi inwestycyjne bez wpisu KNF",
                    legal_basis="art. 76 ustawy o obrocie instrumentami finansowymi",
                    severity="medium",
                    reason="Profil działalności (wealth management / family office / consulting) dotyczy instrumentów finansowych bez zidentyfikowanego wpisu w snapshocie KNF.",
                )
            )

        if has_disguised_edu and has_personal_rec:
            rules.append(
                ViolatedRule(
                    rule_id="M3_DISGUISED_EDUCATION",
                    rule_name="Doradztwo inwestycyjne pod pozorem edukacji",
                    legal_basis="art. 76 ustawy o obrocie instrumentami finansowymi",
                    severity="medium",
                    reason="Deklaracja charakteru edukacyjnego koliduje z ofertą spersonalizowanych wskazań inwestycyjnych.",
                )
            )

    score = round(max(0.0, min(0.96, score)), 4)
    if not quotes and doc.sentences:
        quotes = [doc.sentences[0][:240]]

    model_used = "deterministic-uknf-m3-fallback"
    is_fallback = True

    ctx = context or AnalysisContext()
    assessment = await request_llm_assessment(
        ollama,
        3,
        doc,
        {
            "Tytuł": doc.title,
            "Status w snapshocie KNF": "brak wpisu",
            "Wykryte instrumenty": instruments_found or "brak",
            "Reguły wstępne": [r.rule_id for r in rules] or "brak",
        },
        ctx,
    )
    fused = fuse_module_result(
        doc,
        3,
        score,
        rules,
        quotes,
        assessment,
        llm_weight=0.35,
        hard_commercial=has_personal_rec or has_commercial_cta(text),
        rules_by_id=registry.rules_by_id,
        strict_quotes=ctx.strict_quote_verification,
        max_score=0.96,
    )
    score, rules, quotes = fused.score, fused.rules, fused.quotes
    if fused.used_llm:
        model_used = f"{ollama.active_model} + uknf-m3-art76"
        is_fallback = False
        relevant = relevant or bool(fused.verified_signals)

    entity_title = doc.title.split("—")[0].split("[MOCK")[0].strip() or "Nieautoryzowany podmiot doradczy"

    return ModuleAnalysisResult(
        module_id=3,
        module_name="Identyfikacja usług nieautoryzowanych (Shadow Advisory)",
        relevant=relevant,
        entity_name=entity_title[:120],
        promoter_name=None,
        knf_registry_status="not_in_knf_snapshot",
        risk_score=score,
        evidence_quotes=quotes[:5],
        violated_rules=rules,
        model_used=model_used,
        is_demo_fallback=is_fallback,
    )
