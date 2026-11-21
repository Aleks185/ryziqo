"""Agregator wyników Modułów 1, 2 i 3 w ujednolicone obiekty Incident."""

from __future__ import annotations

import uuid

from app.ai.module1_finfluencers import ModuleAnalysisResult, analyze_module1
from app.ai.module2_risk_compliance import analyze_module2
from app.ai.module3_shadow_advisory import analyze_module3
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.database import score_to_risk_level, utc_now_iso
from app.knf_registry import KNFRegistrySnapshot
from app.models import Incident


async def run_analytical_pipeline(
    doc: PreprocessedDocument,
    module_ids: list[int],
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
    storage_key: str | None = None,
) -> list[Incident]:
    """Run requested analytical modules (1, 2, 3) and aggregate relevant results into Incidents."""
    results: list[ModuleAnalysisResult] = []

    if 1 in module_ids:
        results.append(await analyze_module1(doc, registry, ollama))
    if 2 in module_ids:
        results.append(await analyze_module2(doc, registry, ollama))
    if 3 in module_ids:
        results.append(await analyze_module3(doc, registry, ollama))

    relevant_results = [r for r in results if r.relevant]
    # Always emit at least the highest-scoring module if none matched domain heuristics
    if not relevant_results and results:
        relevant_results = [max(results, key=lambda r: r.risk_score)]

    # If running all 3 modules on a single page, pick primary matching module(s) without noisy duplicates
    if len(module_ids) == 3 and len(relevant_results) > 1:
        # Keep modules that either have concrete violations or the highest relevance score
        with_violations = [r for r in relevant_results if r.violated_rules]
        if with_violations:
            relevant_results = [max(with_violations, key=lambda r: r.risk_score)]
        else:
            relevant_results = [max(relevant_results, key=lambda r: r.risk_score)]

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
                evidence_quotes=res.evidence_quotes,
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
