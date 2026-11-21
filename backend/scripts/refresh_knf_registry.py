"""Refresh the KNF registry snapshot from the official knf.gov.pl lists.

Usage (from backend/):
    python -m scripts.refresh_knf_registry --dry-run     # show the diff, write nothing
    python -m scripts.refresh_knf_registry               # write next to DATABASE_PATH
    python -m scripts.refresh_knf_registry --out ../data/knf_registry_snapshot.json

The running backend picks the refreshed file up on its next start (or immediately via
POST /api/v1/knf-registry/refresh). A category that returns fewer than half of its previous
entities is left unchanged; manual aliases and synthetic demo entries are always kept.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.knf_registry import KNFRegistrySnapshot, pick_snapshot_path  # noqa: E402
from app.knf_sync import fetch_official_sources, merge_snapshot, write_snapshot_atomic  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="tylko raport zmian, bez zapisu")
    parser.add_argument("--out", type=Path, default=None, help="ścieżka wyjściowa (domyślnie obok bazy)")
    args = parser.parse_args()

    settings = get_settings()
    seed = settings.resolved_data_dir / "knf_registry_snapshot.json"
    registry = KNFRegistrySnapshot(
        snapshot_path=pick_snapshot_path(seed, settings.knf_registry_live_path),
        rules_path=settings.resolved_data_dir / "risk_criteria_rules.json",
    )
    old = registry.raw_snapshot
    results = await fetch_official_sources(settings, dict(old.get("official_sources", {})))
    for res in results:
        status = f"BŁĄD: {res.error}" if res.error else f"{len(res.names)} wpisów"
        print(f"- {res.key}: {status}")

    doc, report = merge_snapshot(old, results)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if args.dry_run or doc == old:
        print("Bez zapisu (dry-run lub brak zmian).")
        return 0 if not report.errors else 1

    target = args.out or settings.knf_registry_live_path
    write_snapshot_atomic(target, doc)
    print(f"Zapisano: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
