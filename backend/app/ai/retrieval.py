"""Vector memory over analyst-verified incidents: dynamic few-shot (RAG) and campaign-clone detection.

Uses the vectors already stored in `content_snapshots` (Ollama embedding when available, plus the
deterministic 128-dim feature-hashing vector), so the system learns from analyst labels
(`ground_truth_label`, status confirmed / false_positive) without retraining any model.
Vectors are only compared when their dimensionality matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from app.ai.preprocessor import PreprocessedDocument, cosine_similarity
from app.ai.prompting import RagExample
from app.models import ViolatedRule

RAG_MIN_SIMILARITY = 0.45


class VerifiedVectorSource(Protocol):
    def list_verified_incident_vectors(
        self, exclude_content_hash: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]: ...


@dataclass
class CloneMatch:
    incident_id: str
    module_id: int
    source_url: str
    similarity: float
    risk_score: float
    title: str


def source_domain(url: str) -> str:
    """Registrable-ish host for http(s) URLs (without www.), else the whole URL (mock://, manual://)."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        host = parsed.hostname.lower()
        return host[4:] if host.startswith("www.") else host
    return url.lower()


def best_similarity(doc_vectors: list[list[float]], other_vectors: list[list[float]]) -> float:
    best = 0.0
    for a in doc_vectors:
        for b in other_vectors:
            if a and b and len(a) == len(b):
                best = max(best, cosine_similarity(a, b))
    return best


class Retriever:
    def __init__(
        self,
        source: VerifiedVectorSource,
        clone_threshold: float = 0.85,
        rag_enabled: bool = True,
        rag_min_similarity: float = RAG_MIN_SIMILARITY,
    ) -> None:
        self.source = source
        self.clone_threshold = clone_threshold
        self.rag_enabled = rag_enabled
        self.rag_min_similarity = rag_min_similarity

    def _scored(self, doc: PreprocessedDocument) -> list[tuple[float, dict[str, Any]]]:
        doc_vectors = [v for v in (doc.embedding, doc.local_embedding) if v]
        if not doc_vectors:
            return []
        rows = self.source.list_verified_incident_vectors(exclude_content_hash=doc.content_hash)
        scored = [(best_similarity(doc_vectors, row["vectors"]), row) for row in rows]
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored

    def analyze(
        self, doc: PreprocessedDocument, module_ids: list[int]
    ) -> tuple[dict[int, list[RagExample]], list[CloneMatch]]:
        """Return (module_id -> [top positive, top negative] examples, campaign clones)."""
        scored = self._scored(doc)
        rag: dict[int, list[RagExample]] = {}
        if self.rag_enabled:
            for module_id in module_ids:
                picked: list[RagExample] = []
                for want_label in (True, False):
                    hit = next(
                        (
                            (sim, row)
                            for sim, row in scored
                            if row["module_id"] == module_id
                            and row["label"] is want_label
                            and sim >= self.rag_min_similarity
                            and row["source_url"] != doc.source_url
                        ),
                        None,
                    )
                    if hit:
                        sim, row = hit
                        picked.append(
                            RagExample(
                                label=want_label,
                                similarity=sim,
                                excerpt=row["excerpt"],
                                risk_score=row["risk_score"],
                                rule_ids=row["rule_ids"],
                                analyst_note=row["analyst_note"],
                                incident_id=row["id"],
                            )
                        )
                if picked:
                    rag[module_id] = picked

        doc_domain = source_domain(doc.source_url)
        clones = [
            CloneMatch(
                incident_id=row["id"],
                module_id=row["module_id"],
                source_url=row["source_url"],
                similarity=sim,
                risk_score=row["risk_score"],
                title=row["title"],
            )
            for sim, row in scored
            if sim >= self.clone_threshold
            and row["label"] is True
            and source_domain(row["source_url"]) != doc_domain
        ]
        return rag, clones[:3]


def clone_rule(clone: CloneMatch) -> ViolatedRule:
    return ViolatedRule(
        rule_id="CAMPAIGN_CLONE_MATCH",
        rule_name="Klon potwierdzonej kampanii na innej domenie",
        legal_basis="Pamięć incydentów Ryziqo (potwierdzone przez analityka)",
        severity="high",
        reason=(
            f"Treść w {int(clone.similarity * 100)}% podobna do potwierdzonego incydentu {clone.incident_id} "
            f"({clone.source_url})."
        ),
    )


def clone_boosted_score(score: float, clone: CloneMatch, cap: float = 0.95) -> float:
    """Raise the score towards the confirmed original, scaled by similarity."""
    return round(max(score, min(cap, clone.risk_score * clone.similarity)), 4)
