"""Per-analysis context shared by Modules 1–3 (prompt budget, RAG examples, guard settings)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import PreprocessedDocument
from app.ai.prompting import RagExample, build_system_prompt, build_user_prompt
from app.ai.schemas import LLMAssessment, build_llm_json_schema, parse_llm_assessment


@dataclass
class AnalysisContext:
    prompt_budget_chars: int = 9000
    strict_quote_verification: bool = True
    # module_id -> verified similar incidents used as dynamic few-shot examples
    rag_examples: dict[int, list[RagExample]] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: object) -> AnalysisContext:
        return cls(
            prompt_budget_chars=int(getattr(settings, "ai_prompt_content_chars", 9000)),
            strict_quote_verification=bool(getattr(settings, "ai_strict_quote_verification", True)),
        )


async def request_llm_assessment(
    ollama: OllamaClient,
    module_id: int,
    doc: PreprocessedDocument,
    metadata: dict[str, object],
    ctx: AnalysisContext,
) -> LLMAssessment | None:
    """Ask the local LLM for a structured, schema-constrained assessment; None in fallback mode."""
    if not ollama.is_available:
        return None
    raw = await ollama.generate_json(
        build_system_prompt(module_id),
        build_user_prompt(doc, metadata, ctx.prompt_budget_chars, ctx.rag_examples.get(module_id)),
        json_schema=build_llm_json_schema(module_id),
    )
    return parse_llm_assessment(raw, module_id)
