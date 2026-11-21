"""Initial watchlist: data/watchlist_seed.json + public domains of real entities from the KNF registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.knf_registry import KNFRegistrySnapshot
from app.scraper.urlnorm import site_key


def load_watchlist_seed(seed_path: Path, registry: KNFRegistrySnapshot) -> list[dict[str, Any]]:
    if not seed_path.exists():
        return []
    doc = json.loads(seed_path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = [dict(i) for i in doc.get("items", []) if i.get("url")]
    if not doc.get("include_registry_domains", False):
        return items

    covered = {site_key(i["url"]) for i in items}
    for entity in registry.raw_snapshot.get("entities", []):
        if entity.get("is_synthetic_demo"):
            continue
        for alias in entity.get("aliases", []):
            alias = str(alias).strip().lower()
            if "." not in alias or " " in alias or site_key(f"https://{alias}") in covered:
                continue
            covered.add(site_key(f"https://{alias}"))
            items.append(
                {
                    "url": f"https://{alias}",
                    "label": f"{entity.get('official_name')} (rejestr KNF)",
                    "module_ids": [2, 3],
                }
            )
    return items
