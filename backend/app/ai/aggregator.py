"""Agregator wyników Modułów 1, 2 i 3 w ujednolicone obiekty Incident."""

from __future__ import annotations

import asyncio
import uuid

from app.ai.context import AnalysisContext
from app.ai.module1_finfluencers import ModuleAnalysisResult, analyze_module1
from app.ai.module2_risk_compliance import analyze_module2
from app.ai.module3_shadow_advisory import analyze_module3
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.ai.retrieval import CloneMatch, Retriever, clone_boosted_score, clone_rule
from app.ai.vision_analyzer import analyze_screenshots
from app.database import score_to_risk_level, utc_now_iso
from app.knf_registry import KNFRegistrySnapshot
from app.models import Incident, ViolatedRule

WARNING_LIST_MIN_SCORE = 0.90
IMPERSONATION_MIN_SCORE = 0.75
MULTI_MODULE_MODES = ("primary", "all_significant")


def _apply_finding(
    res: ModuleAnalysisResult,
    rules: list[ViolatedRule],
    min_score: float,
    quotes: list[str],
    cap: float = 1.0,
) -> None:
    existing = {r.rule_id for r in res.violated_rules}
    for rule in rules:
        if rule.rule_id not in existing:
            res.violated_rules.append(rule)
            existing.add(rule.rule_id)
    res.risk_score = round(min(cap, max(res.risk_score, min_score)), 4)
    res.evidence_quotes = [q for q in quotes if q not in res.evidence_quotes] + res.evidence_quotes
    if rules:
        res.relevant = True


def apply_registry_guard(
    results: list[ModuleAnalysisResult], doc: PreprocessedDocument, registry: KNFRegistrySnapshot
) -> None:
    """KNF public-warnings-list hits and brand impersonation raise risk across all modules."""
    links = [*doc.outbound_links, *doc.resolved_links]
    warning = registry.match_warning_list(doc.normalized_text, links)
    if warning:
        demo = " [wpis demonstracyjny]" if warning.is_synthetic_demo else ""
        rule = ViolatedRule(
            rule_id="KNF_WARNING_LIST_MATCH",
            rule_name="Podmiot z Listy Ostrzeżeń Publicznych KNF",
            legal_basis="art. 6b ustawy o nadzorze nad rynkiem finansowym (lista ostrzeżeń publicznych)",
            severity="high",
            reason=f"Trafienie „{warning.matched_text}” → {warning.name} (wpis z {warning.added_date}){demo}.",
        )
        for res in results:
            _apply_finding(res, [rule], WARNING_LIST_MIN_SCORE, [f"[KNF] Lista ostrzeżeń: {warning.name}"])

    impersonations = registry.find_impersonations(doc.normalized_text, links)
    if impersonations:
        imp = impersonations[0]
        kind = "nazwa z dopiskiem (VIP/PRO/Polska…)" if imp.kind == "affix" else "domena łudząco podobna"
        rule = ViolatedRule(
            rule_id="KNF_IMPERSONATION_SUSPECT",
            rule_name="Podejrzenie podszywania się pod licencjonowany podmiot",
            legal_basis="art. 76 i art. 69 ustawy o obrocie instrumentami finansowymi (weryfikacja tożsamości podmiotu)",
            severity="high",
            reason=(
                f"„{imp.token}” przypomina markę {imp.official_name} ({kind}), ale nie jest jej znaną nazwą ani domeną."
            ),
        )
        for res in results:
            res.knf_registry_status = "not_in_knf_snapshot" if res.knf_registry_status == "unknown" else res.knf_registry_status
            _apply_finding(res, [rule], IMPERSONATION_MIN_SCORE, [f"[KNF] Możliwe podszywanie: {imp.token}"])


def apply_clone_matches(results: list[ModuleAnalysisResult], clones: list[CloneMatch]) -> None:
    if not clones or not results:
        return
    clone = clones[0]
    targets = [r for r in results if r.module_id == clone.module_id] or [max(results, key=lambda r: r.risk_score)]
    for res in targets:
        _apply_finding(
            res,
            [clone_rule(clone)],
            clone_boosted_score(res.risk_score, clone),
            [f"[Klon] Podobieństwo {clone.similarity:.2f} do potwierdzonego incydentu {clone.incident_id}"],
            cap=0.95,
        )


async def apply_vision(
    results: list[ModuleAnalysisResult], doc: PreprocessedDocument, ollama: OllamaClient
) -> None:
    if not doc.screenshots or not results:
        return
    outcome = await analyze_screenshots(ollama, doc)
    if outcome is None:
        return
    target = next((r for r in results if r.module_id == 2), None) or max(results, key=lambda r: r.risk_score)
    _apply_finding(target, outcome.rules, outcome.min_score, outcome.quotes, cap=0.97)


def select_results(
    results: list[ModuleAnalysisResult],
    module_ids: list[int],
    multi_module_mode: str = "primary",
    secondary_min_score: float = 0.55,
) -> list[ModuleAnalysisResult]:
    relevant_results = [r for r in results if r.relevant]
    # Always emit at least the highest-scoring module if none matched domain heuristics
    if not relevant_results and results:
        relevant_results = [max(results, key=lambda r: r.risk_score)]

    if len(module_ids) == 3 and len(relevant_results) > 1:
        with_violations = [r for r in relevant_results if r.violated_rules]
        if multi_module_mode == "all_significant":
            significant = [r for r in with_violations if r.risk_score >= secondary_min_score]
            if significant:
                return significant
        # Primary module: concrete violations first, else the highest relevance score
        pool = with_violations or relevant_results
        primary = max(pool, key=lambda r: r.risk_score)
        # Secondary detections are summarized instead of being silently dropped
        for other in results:
            if other is primary or not other.violated_rules or other.risk_score < secondary_min_score:
                continue
            ids = ", ".join(r.rule_id for r in other.violated_rules[:5])
            primary.evidence_quotes.append(
                f"[Wtórne] Moduł {other.module_id} ({other.risk_score:.0%}): {ids}"
            )
        return [primary]
    return relevant_results


async def run_analytical_pipeline(
    doc: PreprocessedDocument,
    module_ids: list[int],
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
    storage_key: str | None = None,
    *,
    retriever: Retriever | None = None,
    context: AnalysisContext | None = None,
    multi_module_mode: str = "primary",
    secondary_min_score: float = 0.55,
) -> list[Incident]:
    """Run requested analytical modules (1, 2, 3) and aggregate relevant results into Incidents."""
    ctx = context or AnalysisContext()
    clones: list[CloneMatch] = []
    if retriever is not None:
        ctx.rag_examples, clones = retriever.analyze(doc, module_ids)

    analyzers = {1: analyze_module1, 2: analyze_module2, 3: analyze_module3}
    # Modules are independent: run their LLM calls concurrently (Ollama queues them if needed)
    results: list[ModuleAnalysisResult] = list(
        await asyncio.gather(
            *(analyzers[m](doc, registry, ollama, ctx) for m in (1, 2, 3) if m in module_ids)
        )
    )

    apply_registry_guard(results, doc, registry)
    apply_clone_matches(results, clones)
    await apply_vision(results, doc, ollama)

    relevant_results = select_results(
        results,
        module_ids,
        multi_module_mode if multi_module_mode in MULTI_MODULE_MODES else "primary",
        secondary_min_score,
    )

    now = utc_now_iso()
    excerpt = doc.normalized_text[:340].strip()
    if len(doc.normalized_text) > 340:
        excerpt += "..."

    incidents: list[Incident] = []
    for res in relevant_results:
        inc_id = f"inc_m{res.module_id}_{uuid.uuid4().hex[:10]}"
        incidents.append(
            Incident(
                id=inc_id,
                module_id=res.module_id,  # type: ignore[arg-type]
                module_name=res.module_name,
                entity_name=res.entity_name,
                promoter_name=res.promoter_name,
                knf_registry_status=res.knf_registry_status,  # type: ignore[arg-type]
                source_platform=doc.source_platform,
                source_url=doc.source_url,
                title=doc.title,
                content_excerpt=excerpt,
                evidence_quotes=res.evidence_quotes[:8],
                violated_rules=res.violated_rules,
                dom_metrics=doc.dom_metrics if res.module_id == 2 else None,
                risk_score=res.risk_score,
                risk_level=score_to_risk_level(res.risk_score),  # type: ignore[arg-type]
                status="new",
                analyst_note=None,
                ground_truth_label=doc.ground_truth_hint,
                model_used=res.model_used,
                is_demo_fallback=res.is_demo_fallback,
                content_hash=doc.content_hash,
                storage_key=storage_key,
                detected_at=now,
                updated_at=now,
            )
        )

    return incidents
