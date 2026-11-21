"""Local KNF investment firms registry snapshot & UKNF risk rules loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MatchedEntity:
    official_name: str
    category: str
    registry_status: str
    country: str
    is_synthetic_demo: bool


class KNFRegistrySnapshot:
    """Loads local KNF registry snapshot with documented date and source disclaimer."""

    def __init__(self, snapshot_path: Path, rules_path: Path) -> None:
        self.snapshot_path = snapshot_path
        self.rules_path = rules_path
        self._snapshot: dict[str, Any] = self._load_json(snapshot_path, default={})
        self._rules_doc: dict[str, Any] = self._load_json(rules_path, default={"rules": []})

    @staticmethod
    def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def snapshot_date(self) -> str:
        return str(self._snapshot.get("snapshot_date", "unknown"))

    @property
    def disclaimer(self) -> str:
        return str(
            self._snapshot.get(
                "disclaimer",
                "Lokalny snapshot demonstracyjny — nie zastępuje bieżącej weryfikacji w rejestrze KNF.",
            )
        )

    @property
    def raw_snapshot(self) -> dict[str, Any]:
        return self._snapshot

    @property
    def risk_rules(self) -> list[dict[str, Any]]:
        return list(self._rules_doc.get("rules", []))

    @property
    def rules_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(r["id"]): r for r in self.risk_rules}

    def match_entity_in_text(self, text: str) -> MatchedEntity | None:
        """Find whether any entity from the local KNF snapshot appears in text."""
        lowered = text.lower()
        for entry in self._snapshot.get("entities", []):
            candidates = [entry.get("official_name", ""), *entry.get("aliases", [])]
            for name in candidates:
                cleaned = name.replace("[DEMO]", "").strip().lower()
                if cleaned and len(cleaned) >= 3 and cleaned in lowered:
                    return MatchedEntity(
                        official_name=str(entry["official_name"]),
                        category=str(entry.get("category", "unknown")),
                        registry_status=str(entry.get("registry_status", "registered_pl")),
                        country=str(entry.get("country", "PL")),
                        is_synthetic_demo=bool(entry.get("is_synthetic_demo", False)),
                    )
        return None
