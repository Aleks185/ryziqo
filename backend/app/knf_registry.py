"""Local KNF investment firms registry snapshot, KNF public warnings list & UKNF risk rules loader."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class MatchedEntity:
    official_name: str
    category: str
    registry_status: str
    country: str
    is_synthetic_demo: bool


@dataclass(frozen=True)
class ImpersonationMatch:
    """A token that looks like a licensed firm's brand but is not one of its known names/domains."""

    token: str
    official_name: str
    registry_status: str
    kind: str  # "affix" (brand + VIP/PRO/Polska...) | "typosquat" (domain at edit distance 1–2)


@dataclass(frozen=True)
class WarningMatch:
    name: str
    matched_text: str
    added_date: str
    is_synthetic_demo: bool


# Words that turn a brand into a "special offer" look-alike (XTB-Polska-VIP, mBank-Inwestycje-Pro)
SUSPICIOUS_AFFIXES = frozenset(
    {
        "vip", "pro", "premium", "elite", "gold", "plus", "max", "official", "oficjalny", "oficjalna",
        "invest", "inwest", "inwestycje", "inwestycja", "investment", "investments", "polska", "poland",
        "bonus", "profit", "zysk", "zyski", "crypto", "krypto", "signals", "sygnaly", "club", "klub",
        "24", "online", "bot", "ai", "trade", "trading", "capital", "wallet", "portfel",
    }
)
# Generic words of official names that must not be used as brand keys
GENERIC_NAME_WORDS = frozenset(
    {
        "biuro", "dom", "maklerski", "maklerskie", "makler", "bank", "banku", "banki", "polska", "polski",
        "polskiego", "polskie", "spolka", "akcyjna", "broker", "brokers", "trade", "trading", "markets",
        "market", "capital", "invest", "investments", "securities", "financial", "finance", "group",
        "europe", "limited", "oddzial", "polsce", "global", "direct", "notyfikacja", "transgraniczna",
        "demo", "app", "etf", "cfd",
    }
)
COMMON_TLDS = frozenset(
    {"com", "pl", "eu", "net", "org", "io", "info", "co", "uk", "de", "biz", "online", "site", "xyz", "app", "pro", "vip", "top"}
)
COMPOUND_TOKEN_RE = re.compile(r"[0-9a-ząćęłńóśźż]+(?:[-_.][0-9a-ząćęłńóśźż]+)+", re.IGNORECASE)
LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def _ascii_fold(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", _ascii_fold(text))


def levenshtein(a: str, b: str, max_dist: int = 3) -> int:
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _snapshot_date_of(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("snapshot_date") or "")
    except (OSError, ValueError):
        return ""


def pick_snapshot_path(seed_path: Path, live_path: Path) -> Path:
    """Use the refreshed snapshot (data volume) when it exists and is not older than the seed copy."""
    if live_path.exists() and live_path.resolve() != seed_path.resolve():
        live_date = _snapshot_date_of(live_path)
        if live_date and live_date >= _snapshot_date_of(seed_path):
            return live_path
    return seed_path


class KNFRegistrySnapshot:
    """Loads local KNF registry snapshot with documented date and source disclaimer."""

    def __init__(self, snapshot_path: Path, rules_path: Path, warnings_path: Path | None = None) -> None:
        self.snapshot_path = snapshot_path
        self.rules_path = rules_path
        self._snapshot: dict[str, Any] = self._load_json(snapshot_path, default={})
        self._rules_doc: dict[str, Any] = self._load_json(rules_path, default={"rules": []})
        if warnings_path is None:
            warnings_path = snapshot_path.parent / "knf_warnings_snapshot.json"
        self._warnings_doc: dict[str, Any] = self._load_json(warnings_path, default={"entries": []})

    def reload(self, snapshot_path: Path | None = None) -> None:
        """Re-read the registry snapshot (after a refresh) and drop the cached brand index."""
        if snapshot_path is not None:
            self.snapshot_path = snapshot_path
        self._snapshot = self._load_json(self.snapshot_path, default={})
        self.__dict__.pop("_brand_index", None)
        self.__dict__.pop("_legit_domains", None)

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
    def warnings_snapshot_date(self) -> str:
        return str(self._warnings_doc.get("snapshot_date", "unknown"))

    @property
    def risk_rules(self) -> list[dict[str, Any]]:
        return list(self._rules_doc.get("rules", []))

    @property
    def rules_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(r["id"]): r for r in self.risk_rules}

    # --- Fuzzy brand matching (typosquatting / impersonation) ---------------------------------
    @cached_property
    def _brand_index(self) -> tuple[list[tuple[str, dict[str, Any]]], set[str]]:
        """(brand_key, entity) pairs and the set of legitimate full names/domains (alnum-folded)."""
        keys: list[tuple[str, dict[str, Any]]] = []
        legit: set[str] = set()
        for entry in self._snapshot.get("entities", []):
            names = [entry.get("official_name", ""), *entry.get("aliases", [])]
            entry_keys: set[str] = set()
            # Fuzzy look-alike keys only for curated brands (manual aliases): the ~750 firms imported
            # from the KNF lists would turn every "capital"/"invest…" domain into a typosquat
            # (money.pl → Monex, capital.com → Lago Kapital). Imported names still count as legit.
            curated = bool(entry.get("aliases"))
            for raw in names:
                name = str(raw).replace("[DEMO]", "").strip()
                if not name:
                    continue
                legit.add(_alnum(name))
                if not curated:
                    continue
                host = name.lower()
                if "." in host and " " not in host:  # a domain alias, e.g. xtb.com
                    label = host.split(".")[0]
                    legit.add(_alnum(label))
                    if len(label) >= 3:
                        entry_keys.add(_alnum(label))
                    continue
                words = re.split(r"[\s()/,-]+", name)
                if len(words) == 1 and len(_alnum(name)) >= 3:
                    entry_keys.add(_alnum(name))
                for w in words:
                    key = _alnum(w)
                    if len(key) >= 4 and key not in GENERIC_NAME_WORDS and not key.isdigit():
                        entry_keys.add(key)
            keys.extend((k, entry) for k in sorted(entry_keys))
        return keys, legit

    @cached_property
    def _legit_domains(self) -> set[str]:
        """Domain aliases of registry entities (e.g. bossa.pl) — their subdomains are the firm's own."""
        domains: set[str] = set()
        for entry in self._snapshot.get("entities", []):
            for raw in entry.get("aliases", []):
                host = str(raw).strip().lower()
                if "." in host and " " not in host:
                    domains.add(host[4:] if host.startswith("www.") else host)
        return domains

    def is_official_host(self, token: str) -> bool:
        """True for a registry entity's own domain or its subdomain (online.bossa.pl → bossa.pl)."""
        host = token.lower().rstrip(".")
        return any(host == d or host.endswith(f".{d}") for d in self._legit_domains)

    @staticmethod
    def _candidate_tokens(text: str, urls: Iterable[str]) -> list[tuple[str, bool]]:
        """(token, is_domain) — compound tokens (XTB-Polska-VIP, xtb-bonus.pl) and link hosts."""
        found: dict[str, bool] = {}
        for m in COMPOUND_TOKEN_RE.finditer(text):
            tok = m.group(0).strip("._-")
            parts = re.split(r"[-_.]", tok.lower())
            found.setdefault(tok, len(parts) >= 2 and parts[-1] in COMMON_TLDS and "." in tok)
        for url in urls:
            host = urlparse(url).hostname
            if host:
                host = host[4:] if host.startswith("www.") else host
                found[host] = True
        return list(found.items())

    def find_impersonations(self, text: str, urls: Iterable[str] = ()) -> list[ImpersonationMatch]:
        keys, legit = self._brand_index
        matches: list[ImpersonationMatch] = []
        seen: set[str] = set()
        for token, is_domain in self._candidate_tokens(text, urls):
            parts = [p for p in re.split(r"[-_.]", _ascii_fold(token)) if p]
            if is_domain and len(parts) >= 2:
                parts = parts[:-1] if parts[-1] in COMMON_TLDS else parts
            folded_parts = [_alnum(p) for p in parts]
            if _alnum(token) in legit or "".join(folded_parts) in legit:
                continue
            if is_domain and self.is_official_host(token):  # online.bossa.pl is bossa.pl, not a look-alike
                continue
            for key, entry in keys:
                hit_kind: str | None = None
                for i, part in enumerate(folded_parts):
                    others = folded_parts[:i] + folded_parts[i + 1 :]
                    if part == key and any(o in SUSPICIOUS_AFFIXES for o in others):
                        hit_kind = "affix"
                    elif part != key and len(key) >= 3 and (
                        (part.startswith(key) and part[len(key):] in SUSPICIOUS_AFFIXES)
                        or (part.endswith(key) and part[: -len(key)] in SUSPICIOUS_AFFIXES)
                    ):
                        hit_kind = "affix"
                    elif (
                        is_domain and len(key) >= 5 and part != key and part not in legit
                        and part not in GENERIC_NAME_WORDS  # bank.pl is a word, not an "mbank" typo
                    ):
                        limit = 1 if len(key) < 8 else 2
                        if levenshtein(part.translate(LEET), key, limit) <= limit:
                            hit_kind = "typosquat"
                    if hit_kind:
                        break
                if hit_kind and token.lower() not in seen:
                    seen.add(token.lower())
                    matches.append(
                        ImpersonationMatch(
                            token=token,
                            official_name=str(entry["official_name"]),
                            registry_status=str(entry.get("registry_status", "registered_pl")),
                            kind=hit_kind,
                        )
                    )
                    break
        return matches

    def match_entity_in_text(self, text: str) -> MatchedEntity | None:
        """Find whether any entity from the local KNF snapshot appears in text.

        Brand look-alikes (e.g. "XTB-Polska-VIP", "xtb-bonus.pl") are masked first, so an impersonator
        is never mistaken for the licensed firm whose name it embeds.
        """
        lowered = text.lower()
        for imp in self.find_impersonations(text):
            lowered = lowered.replace(imp.token.lower(), " ")
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

    # --- KNF public warnings list ("Lista ostrzeżeń publicznych KNF") --------------------------
    def match_warning_list(self, text: str, urls: Iterable[str] = ()) -> WarningMatch | None:
        folded_text = f" {re.sub(r'[^0-9a-z]+', ' ', _ascii_fold(text))} "
        hosts = set()
        for url in urls:
            host = urlparse(url).hostname
            if host:
                hosts.add(host.lower())
        for m in COMPOUND_TOKEN_RE.finditer(text):
            if "." in m.group(0):
                hosts.add(m.group(0).lower().strip("."))
        for entry in self._warnings_doc.get("entries", []):
            name = str(entry.get("name", "")).replace("[DEMO]", "").strip()
            for candidate in [name, *entry.get("aliases", [])]:
                key = re.sub(r"[^0-9a-z]+", " ", _ascii_fold(str(candidate))).strip()
                if len(key) >= 4 and f" {key} " in folded_text:
                    return WarningMatch(
                        name=str(entry.get("name")),
                        matched_text=str(candidate),
                        added_date=str(entry.get("added_date", "")),
                        is_synthetic_demo=bool(entry.get("is_synthetic_demo", False)),
                    )
            for domain in entry.get("domains", []):
                d = str(domain).lower()
                if any(h == d or h.endswith("." + d) for h in hosts):
                    return WarningMatch(
                        name=str(entry.get("name")),
                        matched_text=d,
                        added_date=str(entry.get("added_date", "")),
                        is_synthetic_demo=bool(entry.get("is_synthetic_demo", False)),
                    )
        return None
