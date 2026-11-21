"""Benchmark detection quality on data/eval_golden_dataset.json (Precision / Recall / F1).

Usage (from backend/):
    python -m scripts.evaluate_detection                  # deterministic fallback only
    python -m scripts.evaluate_detection --mode both      # fallback vs. local Ollama
    python -m scripts.evaluate_detection --threshold 0.5 --json-out ../data/eval_report.json

A case is predicted positive when the highest risk_score among emitted incidents >= threshold
(default: HIGH_RISK_ALERT_THRESHOLD). Metrics are reported overall, per expected module and per
category (classic / adversarial / hard_negative), with the list of FP / FN cases for tuning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.aggregator import run_analytical_pipeline  # noqa: E402
from app.ai.context import AnalysisContext  # noqa: E402
from app.ai.ollama_client import OllamaClient  # noqa: E402
from app.ai.preprocessor import PreprocessedDocument, preprocess_html  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.knf_registry import KNFRegistrySnapshot  # noqa: E402
from app.scraper.fetcher import build_manual_text_page  # noqa: E402


@dataclass
class CaseResult:
    id: str
    category: str
    expected_module: int | None
    label: bool
    score: float
    predicted: bool
    predicted_module: int | None
    rule_ids: list[str]
    seconds: float
    model_used: str


def load_case_document(case: dict[str, Any], data_dir: Path) -> PreprocessedDocument:
    if case.get("mock_file"):
        path = data_dir / "mock_sites" / case["mock_file"]
        return preprocess_html(
            path.read_text(encoding="utf-8"), f"mock://{case['mock_file']}", "mock_demo", is_mock_source=True
        )
    if case.get("html"):
        return preprocess_html(case["html"], f"eval://{case['id']}", case.get("platform", "web"))
    page = build_manual_text_page(case["content"], case.get("title"), f"eval://{case['id']}")
    doc = preprocess_html(page.raw_html, page.source_url, page.source_platform)
    if case.get("platform"):
        doc.source_platform = case["platform"]  # simulate the social platform the text came from
    return doc


def metrics(results: list[CaseResult]) -> dict[str, Any]:
    tp = sum(r.predicted and r.label for r in results)
    fp = sum(r.predicted and not r.label for r in results)
    fn = sum(not r.predicted and r.label for r in results)
    tn = sum(not r.predicted and not r.label for r in results)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": len(results), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
    }


async def evaluate(
    cases: list[dict[str, Any]],
    data_dir: Path,
    registry: KNFRegistrySnapshot,
    ollama: OllamaClient,
    settings: Settings,
    threshold: float,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        doc = load_case_document(case, data_dir)
        start = time.perf_counter()
        incidents = await run_analytical_pipeline(
            doc, [1, 2, 3], registry, ollama, context=AnalysisContext.from_settings(settings)
        )
        elapsed = time.perf_counter() - start
        top = max(incidents, key=lambda i: i.risk_score) if incidents else None
        score = top.risk_score if top else 0.0
        results.append(
            CaseResult(
                id=case["id"],
                category=case.get("category", "classic"),
                expected_module=case.get("expected_module"),
                label=bool(case["ground_truth_label"]),
                score=round(score, 4),
                predicted=score >= threshold,
                predicted_module=top.module_id if top else None,
                rule_ids=[r.rule_id for r in top.violated_rules] if top else [],
                seconds=round(elapsed, 3),
                model_used=top.model_used if top else "",
            )
        )
    return results


def report(name: str, results: list[CaseResult], threshold: float) -> dict[str, Any]:
    by_module = {
        f"module_{m}": metrics([r for r in results if r.expected_module == m]) for m in (1, 2, 3)
    }
    by_category = {
        c: metrics([r for r in results if r.category == c]) for c in ("classic", "adversarial", "hard_negative")
    }
    overall = metrics(results)
    errors = [
        {"id": r.id, "type": "FP" if r.predicted else "FN", "score": r.score, "category": r.category,
         "predicted_module": r.predicted_module, "rule_ids": r.rule_ids}
        for r in results if r.predicted != r.label
    ]
    avg_s = sum(r.seconds for r in results) / len(results) if results else 0.0

    print(f"\n=== {name} (threshold {threshold:.2f}, {len(results)} cases, avg {avg_s:.3f}s/case) ===")
    print(f"{'subset':<16}{'n':>4}{'TP':>5}{'FP':>5}{'TN':>5}{'FN':>5}{'P':>8}{'R':>8}{'F1':>8}")
    for label, m in [("overall", overall), *by_module.items(), *by_category.items()]:
        print(
            f"{label:<16}{m['n']:>4}{m['tp']:>5}{m['fp']:>5}{m['tn']:>5}{m['fn']:>5}"
            f"{m['precision']:>8.3f}{m['recall']:>8.3f}{m['f1']:>8.3f}"
        )
    if errors:
        print("Błędy:")
        for e in errors:
            print(f"  {e['type']} {e['id']:<34} score={e['score']:.3f} [{e['category']}] rules={e['rule_ids'][:6]}")
    return {
        "name": name, "threshold": threshold, "avg_seconds_per_case": round(avg_s, 3),
        "overall": overall, "by_module": by_module, "by_category": by_category, "errors": errors,
        "cases": [asdict(r) for r in results],
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["fallback", "ollama", "both"], default="fallback")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    data_dir = settings.resolved_data_dir
    dataset = args.dataset or data_dir / "eval_golden_dataset.json"
    cases = json.loads(dataset.read_text(encoding="utf-8"))["cases"]
    threshold = args.threshold if args.threshold is not None else settings.high_risk_alert_threshold
    registry = KNFRegistrySnapshot(
        snapshot_path=data_dir / "knf_registry_snapshot.json",
        rules_path=data_dir / "risk_criteria_rules.json",
        warnings_path=data_dir / "knf_warnings_snapshot.json",
    )

    reports: list[dict[str, Any]] = []
    if args.mode in ("fallback", "both"):
        offline = OllamaClient(settings)
        offline.is_available = False
        reports.append(report("demo_fallback (reguły)", await evaluate(cases, data_dir, registry, offline, settings, threshold), threshold))
    if args.mode in ("ollama", "both"):
        live = OllamaClient(settings)
        if not await live.check_health():
            print(f"\nOllama niedostępna pod {settings.ollama_base_url} — pomijam tryb ollama.")
        else:
            reports.append(report(f"ollama ({live.active_model})", await evaluate(cases, data_dir, registry, live, settings, threshold), threshold))

    if args.json_out:
        args.json_out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nZapisano raport: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
