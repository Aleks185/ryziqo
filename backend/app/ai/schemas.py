"""Structured LLM output schemas, per-module semantic signal catalogue and the anti-hallucination guard.

The LLM no longer returns a single opaque `risk_score`. It returns a context classification, a short
reasoning (written *before* the score, a light chain-of-thought), a checklist of semantic signals, each
backed by an `exact_quote` from the analyzed text, and its own score. Quotes are verified against the
source document; signals with fabricated quotes are dropped (or downgraded in non-strict mode).
"""

from __future__ import annotations

import difflib
import re
import string
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.ai.preprocessor import deobfuscate_text

ContextType = Literal[
    "commercial_ad", "affiliate_promo", "advisory_offer", "educational", "journalism_warning", "other"
]
SignalStrength = Literal["absent", "subtle", "explicit"]
CONTEXT_TYPES: tuple[str, ...] = (
    "commercial_ad", "affiliate_promo", "advisory_offer", "educational", "journalism_warning", "other"
)
NON_COMMERCIAL_CONTEXTS = frozenset({"educational", "journalism_warning"})


@dataclass(frozen=True)
class SignalSpec:
    """A semantic signal the LLM checks for, and the ViolatedRule it maps to when verified."""

    signal_id: str
    description: str  # shown to the LLM (Polish)
    rule_id: str
    rule_name: str
    legal_basis: str
    severity: Literal["low", "medium", "high"] = "medium"


SIGNAL_CATALOGUE: dict[int, tuple[SignalSpec, ...]] = {
    1: (
        SignalSpec(
            "undisclosed_promotion",
            "ukryta współpraca / afiliacja: linki, kody, polecenia brokera bez oznaczenia #reklama/#współpraca",
            "M1_UNDISCLOSED_AD",
            "Brak jednoznacznego oznaczenia współpracy reklamowej",
            "art. 24 ust. 3 MiFID II / praktyki finfluencerów",
            "high",
        ),
        SignalSpec(
            "profit_promise_without_risk",
            "eufemizmy i obietnice zysku (np. 'pewniak', 'odpalam rakietę', 'kasa sama wpada') bez ostrzeżenia o ryzyku",
            "3",
            "Brak informacji o ryzyku przy obietnicy zysku",
            "art. 44 ust. 2 lit. b rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "fomo_pressure",
            "presja czasu / FOMO: 'ostatnie miejsca', 'tylko dziś', 'nie przegap'",
            "AI_M1_FOMO_PRESSURE",
            "Presja czasu (FOMO) w promocji inwestycji",
            "art. 24 ust. 3 MiFID II (rzetelność i niewprowadzanie w błąd)",
            "medium",
        ),
        SignalSpec(
            "crossborder_broker_promo",
            "polskojęzyczna promocja zagranicznego brokera / platformy bez oddziału w Polsce",
            "M1_CROSSBORDER_PROMO",
            "Polskojęzyczna promocja zagranicznej firmy inwestycyjnej",
            "Zakres Modułu 1 UKNF (działalność transgraniczna)",
            "medium",
        ),
        SignalSpec(
            "copy_trading_signals_vip",
            "copy-trading, płatne grupy sygnałowe, 'VIP' na Telegramie/Discordzie",
            "AI_M1_SIGNAL_GROUP",
            "Promocja grup sygnałowych / copy-tradingu",
            "art. 69 i art. 76 ustawy o obrocie instrumentami finansowymi",
            "high",
        ),
    ),
    2: (
        SignalSpec(
            "profit_risk_asymmetry",
            "asymetria przekazu: zyski wyeksponowane, ryzyko pominięte lub zmarginalizowane",
            "3",
            "Informacja o ryzyku",
            "art. 44 ust. 2 lit. b rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "implied_knf_endorsement",
            "pośrednie sugerowanie aprobaty / zatwierdzenia produktu przez KNF lub inny organ",
            "17",
            "Zakaz sugerowania aprobaty organu nadzoru",
            "art. 44 ust. 8 rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "supervision_as_safety",
            "nadzór KNF przedstawiany jako gwarancja bezpieczeństwa inwestycji",
            "18",
            "Nadzór jako argument bezpieczeństwa",
            "art. 44 ust. 8 rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "cherry_picked_performance",
            "wybiórcze wyniki historyczne (najlepszy okres, brak 5 lat, brak źródła)",
            "12a",
            "Wyniki historyczne — okres i zakres",
            "art. 44 ust. 4 rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "unqualified_forecast",
            "prognoza przyszłych zysków bez zastrzeżenia o braku wiarygodności",
            "15",
            "Prognozy przyszłych wyników",
            "art. 44 ust. 6 rozporządzenia del. 2017/565",
            "high",
        ),
        SignalSpec(
            "vague_tax_promise",
            "niejasne obietnice korzyści podatkowych bez zależności od sytuacji klienta",
            "16",
            "Informacja podatkowa",
            "art. 44 ust. 7 rozporządzenia del. 2017/565",
            "medium",
        ),
        SignalSpec(
            "unsourced_comparison",
            "porównania z rynkiem / konkurencją bez źródła i metodologii",
            "11",
            "Porównania produktów / usług",
            "art. 44 ust. 3 rozporządzenia del. 2017/565",
            "medium",
        ),
    ),
    3: (
        SignalSpec(
            "personalized_portfolio",
            "spersonalizowany dobór portfela / rekomendacje 'pod Ciebie' dotyczące instrumentów finansowych",
            "M3_ART76_PERSONAL_REC",
            "Podejrzenie nieautoryzowanego doradztwa inwestycyjnego",
            "art. 76 oraz art. 2 i 3 ustawy o obrocie instrumentami finansowymi",
            "high",
        ),
        SignalSpec(
            "disguised_mentoring",
            "doradztwo pod pozorem edukacji / mentoringu / 'tylko edukacja'",
            "M3_DISGUISED_EDUCATION",
            "Doradztwo inwestycyjne pod pozorem edukacji",
            "art. 76 ustawy o obrocie instrumentami finansowymi",
            "medium",
        ),
        SignalSpec(
            "success_fee",
            "wynagrodzenie zależne od wyników inwestycji klienta (success fee, % od zysku)",
            "AI_M3_SUCCESS_FEE",
            "Wynagrodzenie od wyników (success fee) za wskazania inwestycyjne",
            "art. 76 ustawy o obrocie instrumentami finansowymi",
            "high",
        ),
        SignalSpec(
            "specific_instrument_calls",
            "wskazania konkretnych instrumentów do kupna/sprzedaży/trzymania (akcje, obligacje, ETF, CFD)",
            "AI_M3_INSTRUMENT_CALLS",
            "Wskazania konkretnych instrumentów finansowych przez podmiot nieautoryzowany",
            "art. 2 i 3 ustawy o obrocie instrumentami finansowymi",
            "high",
        ),
        SignalSpec(
            "unlicensed_asset_management",
            "zarządzanie cudzym portfelem / pełnomocnictwo do rachunku maklerskiego bez licencji",
            "M3_UNLICENSED_WEALTH_PROFILE",
            "Podmiot wealth/consulting oferujący usługi inwestycyjne bez wpisu KNF",
            "art. 69 i art. 76 ustawy o obrocie instrumentami finansowymi",
            "high",
        ),
    ),
}


def signal_specs(module_id: int) -> dict[str, SignalSpec]:
    return {s.signal_id: s for s in SIGNAL_CATALOGUE.get(module_id, ())}


class SemanticSignal(BaseModel):
    signal_id: str
    strength: SignalStrength = "absent"
    exact_quote: str = ""
    explanation: str = ""

    @field_validator("strength", mode="before")
    @classmethod
    def _coerce_strength(cls, v: Any) -> str:
        v = str(v or "absent").strip().lower()
        return v if v in ("absent", "subtle", "explicit") else "absent"


class LLMAssessment(BaseModel):
    context_type: ContextType = "other"
    reasoning: str = ""
    signals: list[SemanticSignal] = Field(default_factory=list)
    llm_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    summary_reason: str = ""

    @field_validator("context_type", mode="before")
    @classmethod
    def _coerce_context(cls, v: Any) -> str:
        v = str(v or "other").strip().lower()
        return v if v in CONTEXT_TYPES else "other"

    @field_validator("llm_risk_score", mode="before")
    @classmethod
    def _clamp_score(cls, v: Any) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


def build_llm_json_schema(module_id: int) -> dict[str, Any]:
    """Self-contained JSON Schema (no $ref) for Ollama structured outputs, `signal_id` as an enum."""
    signal_ids = [s.signal_id for s in SIGNAL_CATALOGUE.get(module_id, ())]
    return {
        "type": "object",
        "properties": {
            "context_type": {"type": "string", "enum": list(CONTEXT_TYPES)},
            "reasoning": {"type": "string"},
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "signal_id": {"type": "string", "enum": signal_ids},
                        "strength": {"type": "string", "enum": ["absent", "subtle", "explicit"]},
                        "exact_quote": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["signal_id", "strength", "exact_quote", "explanation"],
                },
            },
            "llm_risk_score": {"type": "number", "minimum": 0, "maximum": 1},
            "summary_reason": {"type": "string"},
        },
        "required": ["context_type", "reasoning", "signals", "llm_risk_score", "summary_reason"],
    }


def parse_llm_assessment(data: dict[str, Any] | None, module_id: int) -> LLMAssessment | None:
    """Lenient validation of model output (small local models drift); None when unusable.

    Accepts the legacy flat `{"risk_score": ...}` shape so older prompts / models keep working.
    Signals with unknown ids are dropped.
    """
    if not isinstance(data, dict):
        return None
    payload = dict(data)
    if "llm_risk_score" not in payload and isinstance(payload.get("risk_score"), (int, float)):
        payload["llm_risk_score"] = payload["risk_score"]
    if not isinstance(payload.get("llm_risk_score"), (int, float)):
        return None
    if not payload.get("summary_reason"):
        payload["summary_reason"] = str(payload.get("key_finding") or "")
    allowed = signal_specs(module_id)
    raw_signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
    signals: list[dict[str, Any]] = []
    for item in raw_signals:
        if isinstance(item, dict) and str(item.get("signal_id")) in allowed:
            signals.append(
                {
                    "signal_id": str(item.get("signal_id")),
                    "strength": item.get("strength"),
                    "exact_quote": str(item.get("exact_quote") or "")[:400],
                    "explanation": str(item.get("explanation") or "")[:400],
                }
            )
    payload["signals"] = signals
    payload["reasoning"] = str(payload.get("reasoning") or "")[:1500]
    payload["summary_reason"] = str(payload.get("summary_reason") or "")[:500]
    try:
        return LLMAssessment.model_validate(
            {k: payload.get(k) for k in LLMAssessment.model_fields if k in payload}
        )
    except ValidationError:
        return None


# --- Anti-Hallucination Guard ------------------------------------------------------------------
_PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation + "„”“‚’‘«»–—…"})
QuoteMatch = Literal["exact", "fuzzy", "missing"]


def _canonical(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text, _ = deobfuscate_text(text)
    text = text.casefold().translate(_PUNCT_TABLE)
    return re.sub(r"\s+", " ", text).strip()


def verify_quote_in_document(quote: str, normalized_text: str, min_ratio: float = 0.85) -> QuoteMatch:
    """Check that an LLM quote really occurs in the analyzed text.

    "exact": verbatim after case/punctuation/whitespace normalization; "fuzzy": the longest common
    block covers >= `min_ratio` of the quote (tolerates small paraphrase/typo by the model);
    "missing": not found (likely hallucinated). Quotes under 8 characters cannot prove anything.
    """
    q = _canonical(quote)
    if len(q) < 8:
        return "missing"
    doc = _canonical(normalized_text)
    if q in doc:
        return "exact"
    # Align the quote on its longest common block, then compare the whole aligned window
    # (tolerates inflection / typos anywhere in the quote, not only at its ends)
    match = difflib.SequenceMatcher(None, q, doc, autojunk=False).find_longest_match(0, len(q), 0, len(doc))
    if match.size >= 6:
        start = max(0, match.b - match.a)
        for pad in (0, 4, 10):
            window = doc[max(0, start - pad): start + len(q) + pad]
            if difflib.SequenceMatcher(None, q, window, autojunk=False).ratio() >= min_ratio:
                return "fuzzy"
    # Tolerate an ellipsis-joined quote ("A ... B"): every long fragment must exist
    parts = [p for p in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if len(_canonical(p)) >= 8]
    if len(parts) > 1 and all(_canonical(p) in doc for p in parts):
        return "fuzzy"
    return "missing"
