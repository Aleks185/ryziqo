"""Evidence pack (chain of custody) and version history of monitored pages.

The ZIP bundles everything stored for an incident (raw HTML, extraction JSON, screenshots, the
incident record and its technical report) with a SHA-256 manifest, optionally time-stamped by an
RFC 3161 Time Stamping Authority. Version history compares stored snapshots of the same URL and
flags a risk warning that disappeared or shrank between scans ("vanishing warning").
"""

from __future__ import annotations

import difflib
import hashlib
import io
import json
import logging
import re
import secrets
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.ai.module2_risk_compliance import EN_RISK_ONLY_RE, PL_RISK_WARNING_RE
from app.models import IncidentDetail, ViolatedRule

logger = logging.getLogger("ryziqo.evidence")

# A risk-warning font at least this much smaller than in the previous scan counts as "shrunk"
FONT_SHRINK_RATIO = 0.75
MAX_DIFF_LINES = 40
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def has_risk_warning(text: str) -> bool:
    return bool(PL_RISK_WARNING_RE.search(text) or EN_RISK_ONLY_RE.search(text))


def _risk_font(version: dict[str, Any]) -> float | None:
    value = (version.get("dom_metrics") or {}).get("risk_font_px")
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def sentence_diff(old: str, new: str) -> dict[str, list[str]]:
    """Sentences removed from / added to the page between two versions (capped)."""
    a = [s.strip() for s in SENTENCE_SPLIT_RE.split(old) if s.strip()]
    b = [s.strip() for s in SENTENCE_SPLIT_RE.split(new) if s.strip()]
    removed: list[str] = []
    added: list[str] = []
    for line in difflib.ndiff(a, b):
        if line.startswith("- "):
            removed.append(line[2:][:300])
        elif line.startswith("+ "):
            added.append(line[2:][:300])
    return {"removed": removed[:MAX_DIFF_LINES], "added": added[:MAX_DIFF_LINES]}


@dataclass
class WarningChange:
    previous_fetched_at: str
    current_fetched_at: str
    kind: str  # "removed" | "shrunk"
    previous_font_px: float | None = None
    current_font_px: float | None = None

    def rule(self) -> ViolatedRule:
        if self.kind == "removed":
            detail = "ostrzeżenie o ryzyku obecne w poprzedniej wersji zniknęło ze strony"
        else:
            detail = (
                f"czcionka ostrzeżenia o ryzyku zmniejszona z {self.previous_font_px:g} px "
                f"do {self.current_font_px:g} px"
            )
        return ViolatedRule(
            rule_id="RISK_WARNING_REMOVED",
            rule_name="Znikające ostrzeżenie o ryzyku między skanami",
            legal_basis="art. 44 ust. 2 lit. b rozporządzenia del. 2017/565 (historia wersji Ryziqo)",
            severity="high",
            reason=(
                f"Porównanie wersji {self.previous_fetched_at} → {self.current_fetched_at}: {detail}."
            ),
        )


def detect_warning_change(previous: dict[str, Any], current: dict[str, Any]) -> WarningChange | None:
    """Compare two versions (dicts with normalized_text, dom_metrics, fetched_at)."""
    before = has_risk_warning(previous.get("normalized_text", ""))
    after = has_risk_warning(current.get("normalized_text", ""))
    common = dict(
        previous_fetched_at=str(previous.get("fetched_at", "?")),
        current_fetched_at=str(current.get("fetched_at", "?")),
    )
    if before and not after:
        return WarningChange(kind="removed", **common)
    old_font, new_font = _risk_font(previous), _risk_font(current)
    if before and after and old_font and new_font and new_font <= old_font * FONT_SHRINK_RATIO:
        return WarningChange(kind="shrunk", previous_font_px=old_font, current_font_px=new_font, **common)
    return None


def version_history(versions: list[dict[str, Any]], current_hash: str | None) -> dict[str, Any]:
    """Public view of stored versions (oldest first) plus the diff of the last change."""
    items = [
        {
            "content_hash": v["content_hash"],
            "fetched_at": v["fetched_at"],
            "has_risk_warning": has_risk_warning(v["normalized_text"]),
            "risk_font_px": _risk_font(v),
            "is_current": v["content_hash"] == current_hash,
        }
        for v in versions
    ]
    result: dict[str, Any] = {"versions": items, "last_change": None}
    if len(versions) >= 2:
        prev, cur = versions[-2], versions[-1]
        change = detect_warning_change(prev, cur)
        result["last_change"] = {
            "from": prev["content_hash"],
            "to": cur["content_hash"],
            "warning_change": change.kind if change else None,
            **sentence_diff(prev["normalized_text"], cur["normalized_text"]),
        }
    return result


# --- RFC 3161 --------------------------------------------------------------------------------

def _der(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + body


def _der_int(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=False)
    return _der(0x02, raw)


SHA256_ALGORITHM = _der(0x30, _der(0x06, bytes.fromhex("608648016503040201")) + b"\x05\x00")


def timestamp_request(digest: bytes, nonce: int) -> bytes:
    """DER TimeStampReq (RFC 3161 §2.4.1): v1, SHA-256 imprint, nonce, certReq=TRUE."""
    imprint = _der(0x30, SHA256_ALGORITHM + _der(0x04, digest))
    return _der(0x30, _der_int(1) + imprint + _der_int(nonce) + b"\x01\x01\xff")


def timestamp_status(response: bytes) -> int | None:
    """PKIStatus of a TimeStampResp (0 granted, 1 granted with mods); None when malformed."""
    try:
        # TimeStampResp SEQUENCE -> PKIStatusInfo SEQUENCE -> INTEGER status
        pos = 0
        for _ in range(2):
            if response[pos] != 0x30:
                return None
            pos += 2 + (response[pos + 1] & 0x7F if response[pos + 1] & 0x80 else 0)
        if response[pos] != 0x02:
            return None
        size = response[pos + 1]
        return int.from_bytes(response[pos + 2: pos + 2 + size], "big")
    except IndexError:
        return None


async def request_timestamp(tsa_url: str, digest: bytes, timeout: float = 10.0) -> tuple[bytes | None, str]:
    """Ask a TSA for a token over `digest`. Returns (raw TimeStampResp or None, note)."""
    nonce = secrets.randbits(63)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            res = await client.post(
                tsa_url,
                content=timestamp_request(digest, nonce),
                headers={"Content-Type": "application/timestamp-query"},
            )
    except httpx.HTTPError as exc:
        return None, f"TSA niedostępne: {exc.__class__.__name__}"
    if res.status_code != 200:
        return None, f"TSA zwróciło HTTP {res.status_code}"
    status = timestamp_status(res.content)
    if status not in (0, 1):
        return None, f"TSA odrzuciło żądanie (status {status})"
    return res.content, "Znacznik czasu RFC 3161 dołączony (manifest.tsr)."


# --- Evidence pack ---------------------------------------------------------------------------

def _store_file(object_store: Path, name: str | None) -> bytes | None:
    if not name:
        return None
    path = (object_store / Path(name).name)
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


async def build_evidence_pack(
    incident: IncidentDetail,
    object_store: Path,
    report: dict[str, Any] | None,
    versions: dict[str, Any],
    app_version: str,
    tsa_url: str | None = None,
) -> bytes:
    files: dict[str, bytes] = {}
    content_hash = incident.content_hash or ""
    if content_hash:
        if (html := _store_file(object_store, f"{content_hash}.html")) is not None:
            files["source.html"] = html
        for candidate in sorted(object_store.glob(f"{content_hash}_*")):
            if candidate.suffix.lower() in (".png", ".jpg", ".jpeg"):
                files[f"screenshots/{candidate.name}"] = candidate.read_bytes()
    if (artifact := _store_file(object_store, incident.storage_key)) is not None:
        files["extraction.json"] = artifact
    files["incident.json"] = incident.model_dump_json(indent=2).encode("utf-8")
    if report is not None:
        files["report.json"] = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    files["versions.json"] = json.dumps(versions, ensure_ascii=False, indent=2).encode("utf-8")

    manifest: dict[str, Any] = {
        "generator": f"Ryziqo {app_version}",
        "incident_id": incident.id,
        "source_url": incident.source_url,
        "content_hash": incident.content_hash,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hash_algorithm": "SHA-256",
        "files": [
            {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(files.items())
        ],
        "notes": [],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    token: bytes | None = None
    if tsa_url:
        # The token signs exactly the manifest.json bytes; on failure the manifest gets a note instead
        token, note = await request_timestamp(tsa_url, hashlib.sha256(manifest_bytes).digest())
        if token is None:
            logger.warning("Evidence pack %s: %s", incident.id, note)
            manifest["notes"].append(note)
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(files.items()):
            zf.writestr(path, data)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("manifest.sha256", f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n")
        if token is not None:
            zf.writestr("manifest.tsr", token)
    return buf.getvalue()
