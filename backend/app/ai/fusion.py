"""Non-linear fusion of deterministic UKNF rules with verified LLM evidence.

Replaces the old linear blend (`0.65 * rules + 0.35 * llm`), which
- suppressed AI detections of paraphrases/slang that no regex matches (FN): `0.65*0.12 + 0.35*0.95 = 0.41`,
- could not correct rule hits on educational / warning articles quoting scams (FP).

Final score = max(rule_score, linear_blend, ai_verified_score), followed by a context veto:
- ai_verified_score only counts signals whose `exact_quote` was found in the source text
  (Anti-Hallucination Guard) and is capped by the model's own `llm_risk_score`,
- the veto lowers the score for "educational" / "journalism_warning" content only when there are no
  hard commercial signals (affiliate links, sign-up CTA, paid offer), no verified explicit AI signals
  and no prompt-injection attempt (an injected page must not be able to talk its way down).
Without an LLM answer the deterministic result is returned unchanged (demo_fallback parity), apart
from the deterministic prompt-injection rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.preprocessor import PreprocessedDocument
from app.ai.schemas import (
    NON_COMMERCIAL_CONTEXTS,
    LLMAssessment,
    SemanticSignal,
    signal_specs,
    verify_quote_in_document,
)
from app.models import ViolatedRule

COMMERCIAL_CTA_RE = re.compile(
    r"(załóż\s+konto|otwórz\s+(?:rachunek|konto)|zarejestruj|zapisz\s+się|kup\s+(?:teraz|dostęp)|"
    r"dołącz\s+(?:do|teraz)|odbierz\s+(?:bonus|dostęp)|kod\w*\s+(?:promocyjn|polecaj|rabatow)|link\w*\s+w\s+bio|"
    r"link\w*\s+partnersk|reflink|zł\s*/\s*(?:mies|msc|miesiąc)|płatn\w+\s+konsultac|umów\s+(?:się\s+na\s+)?konsultac|"
    r"success\s+fee|wpłać|pierwsz\w+\s+depozyt|cena\s*:?\s*\d)",
    re.IGNORECASE,
)

VETO_SCORE_CAP = 0.35
INJECTION_MIN_SCORE = 0.65
QUOTE_WEIGHT = {"exact": 1.0, "fuzzy": 0.85, "missing": 0.0}
STRENGTH_WEIGHT = {"explicit": 1.0, "subtle": 0.4, "absent": 0.0}


def has_commercial_cta(text: str) -> bool:
    return bool(COMMERCIAL_CTA_RE.search(text))


@dataclass
class VerifiedSignal:
    signal: SemanticSignal
    match: str  # exact | fuzzy | missing
    weight: float


@dataclass
class FusionResult:
    score: float
    rules: list[ViolatedRule]
    quotes: list[str]
    used_llm: bool
    vetoed: bool = False
    ai_verified_score: float = 0.0
    verified_signals: list[VerifiedSignal] = field(default_factory=list)
    rejected_signals: list[SemanticSignal] = field(default_factory=list)


def verify_signals(
    assessment: LLMAssessment, text: str, strict: bool = True
) -> tuple[list[VerifiedSignal], list[SemanticSignal]]:
    verified: list[VerifiedSignal] = []
    rejected: list[SemanticSignal] = []
    for sig in assessment.signals:
        base = STRENGTH_WEIGHT.get(sig.strength, 0.0)
        if base == 0.0:
            continue
        match = verify_quote_in_document(sig.exact_quote, text)
        weight = base * QUOTE_WEIGHT[match]
        if match == "missing":
            if strict:
                rejected.append(sig)
                continue
            weight = base * 0.2  # non-strict: unverifiable claims keep a token weight
        verified.append(VerifiedSignal(signal=sig, match=match, weight=round(weight, 3)))
    return verified, rejected


def _rule_from_signal(
    module_id: int, vs: VerifiedSignal, rules_by_id: dict[str, dict]
) -> ViolatedRule | None:
    spec = signal_specs(module_id).get(vs.signal.signal_id)
    if spec is None:
        return None
    meta = rules_by_id.get(spec.rule_id, {})
    quote = vs.signal.exact_quote.strip()[:180]
    explanation = vs.signal.explanation.strip()[:220] or spec.description
    return ViolatedRule(
        rule_id=spec.rule_id,
        rule_name=str(meta.get("name", spec.rule_name)),
        legal_basis=str(meta.get("legal_basis", spec.legal_basis)),
        severity=spec.severity,
        reason=f"[AI] {explanation} — cytat: „{quote}”",
    )


def injection_rule(doc: PreprocessedDocument) -> ViolatedRule:
    where = "w ukrytym tekście" if doc.hidden_text_detected else "w treści"
    return ViolatedRule(
        rule_id="AI_PROMPT_INJECTION",
        rule_name="Próba manipulacji systemem analizy (prompt injection / cloaking)",
        legal_basis="Sygnał techniczny #InvestWatch — wymaga weryfikacji analityka",
        severity="high",
        reason=(
            f"Wykryto polecenia skierowane do systemu oceny {where}: "
            + ", ".join(f"„{s[:60]}”" for s in doc.injection_snippets[:3])
        ),
    )


def fuse_module_result(
    doc: PreprocessedDocument,
    module_id: int,
    rule_score: float,
    rules: list[ViolatedRule],
    quotes: list[str],
    assessment: LLMAssessment | None,
    *,
    llm_weight: float,
    hard_commercial: bool,
    rules_by_id: dict[str, dict] | None = None,
    strict_quotes: bool = True,
    max_score: float = 0.97,
    max_quotes: int = 5,
) -> FusionResult:
    rules = list(rules)
    quotes = list(quotes)
    rules_by_id = rules_by_id or {}
    score = rule_score

    if doc.prompt_injection_detected:
        if not any(r.rule_id == "AI_PROMPT_INJECTION" for r in rules):
            rules.append(injection_rule(doc))
        score = max(score, INJECTION_MIN_SCORE)

    if assessment is None:
        return FusionResult(score=round(min(max_score, score), 4), rules=rules, quotes=quotes, used_llm=False)

    llm_score = assessment.llm_risk_score
    blended = (1.0 - llm_weight) * rule_score + llm_weight * llm_score

    verified, rejected = verify_signals(assessment, doc.normalized_text, strict=strict_quotes)
    evidence = sum(v.weight for v in verified)
    ai_verified = 0.0
    if evidence >= 1.0:
        ai_verified = min(llm_score, 0.62 + 0.10 * (evidence - 1.0), 0.95)

    existing_ids = {r.rule_id for r in rules}
    for vs in verified:
        if vs.signal.strength != "explicit" or vs.match == "missing":
            continue
        quote = vs.signal.exact_quote.strip()[:260]
        if quote and quote not in quotes:
            quotes.append(quote)
        rule = _rule_from_signal(module_id, vs, rules_by_id)
        if rule and rule.rule_id not in existing_ids:
            rules.append(rule)
            existing_ids.add(rule.rule_id)

    score = max(score, blended, ai_verified)

    vetoed = False
    lead_notes: list[str] = []
    has_explicit = any(v.signal.strength == "explicit" and v.match != "missing" for v in verified)
    if (
        assessment.context_type in NON_COMMERCIAL_CONTEXTS
        and not hard_commercial
        and not has_explicit
        and not doc.prompt_injection_detected
        and score > VETO_SCORE_CAP
    ):
        score = VETO_SCORE_CAP
        vetoed = True
        rules = [r.model_copy(update={"severity": "low"}) for r in rules]
        label = "edukacyjny" if assessment.context_type == "educational" else "ostrzegawczy / dziennikarski"
        lead_notes.append(
            f"[AI-Context] Kontekst {label} bez sygnałów komercyjnych (CTA, afiliacja, płatna oferta) "
            "— obniżono ocenę; reguły zachowano do weryfikacji."
        )

    tail_notes: list[str] = []
    if rejected:
        tail_notes.append(
            f"[AI-Guard] Odrzucono {len(rejected)} sygnał(y) LLM bez potwierdzenia cytatem w treści."
        )
    reason = assessment.summary_reason.strip()
    if reason:
        tail_notes.append(f"[AI] {reason[:220]}")
    room = max(1, max_quotes - len(lead_notes) - len(tail_notes))
    quotes = lead_notes + quotes[:room] + tail_notes

    return FusionResult(
        score=round(max(0.0, min(max_score, score)), 4),
        rules=rules,
        quotes=quotes,
        used_llm=True,
        vetoed=vetoed,
        ai_verified_score=round(ai_verified, 4),
        verified_signals=verified,
        rejected_signals=rejected,
    )
