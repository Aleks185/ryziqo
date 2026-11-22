"""Relationship graph of incidents: promoters, domains, link targets, referral codes and campaigns.

Built on demand from the incidents table, the stored extraction artifacts (outbound and resolved
links) and the threat-report campaigns, so the analyst can see one distribution network behind
several adverts (the same finfluencer, the same referral code, a cloned landing page).
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.threat_intel import domain_of, platforms

REFERRAL_PARAMS = re.compile(r"^(?:ref|refid|referral|aff|affid|affiliate|code|promo|promocode|invite|partner|utm_campaign)$", re.I)
CLONE_ID_RE = re.compile(r"potwierdzonego incydentu (\S+) \(")
UNKNOWN_ENTITIES = {"", "nieznany", "unknown", "brak reklamowanej firmy inwestycyjnej", "niezidentyfikowany podmiot promowany"}


class GraphBuilder:
    def __init__(self, max_nodes: int) -> None:
        self.max_nodes = max_nodes
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.truncated = False

    def node(self, kind: str, key: str, label: str, **attrs: Any) -> str | None:
        node_id = f"{kind}:{key}"
        if node_id in self.nodes:
            self.nodes[node_id]["weight"] += 1
            return node_id
        if len(self.nodes) >= self.max_nodes:
            self.truncated = True
            return None
        self.nodes[node_id] = {"id": node_id, "type": kind, "label": label[:80], "weight": 1, **attrs}
        return node_id

    def edge(self, source: str | None, target: str | None, kind: str) -> None:
        if source and target and source != target:
            self.edges.setdefault((source, target, kind), {"source": source, "target": target, "type": kind})


def referral_codes(url: str) -> list[str]:
    try:
        query = urlsplit(url).query
    except ValueError:
        return []
    return [f"{k}={v}"[:60] for k, v in parse_qsl(query) if REFERRAL_PARAMS.match(k) and v.strip()]


REJECTED = ("false_positive", "dismissed")


def clone_originals(rule: Any) -> list[str]:
    """Confirmed originals of a CAMPAIGN_CLONE_MATCH rule (structured field; regex only for old rows)."""
    if rule.related_incident_ids:
        return list(rule.related_incident_ids)
    m = CLONE_ID_RE.search(rule.reason or "")
    return [m.group(1)] if m else []


def build_graph(db: Any, intel: Any, min_score: float = 0.5, limit: int = 200, max_nodes: int = 400) -> dict[str, Any]:
    # Rejected incidents are filtered in SQL, so they do not use up the `limit` budget
    incidents, _ = db.list_incidents(min_risk_score=min_score, limit=limit, exclude_statuses=REJECTED)
    # Confirmed originals of clones may be older than the window: fetch them, or the clone_of edge is lost
    present = {i.id for i in incidents}
    for inc in list(incidents):
        for rule in inc.violated_rules:
            if rule.rule_id != "CAMPAIGN_CLONE_MATCH":
                continue
            for original_id in clone_originals(rule):
                if original_id in present:
                    continue
                original = db.get_incident(original_id)
                if original is not None and original.status not in REJECTED:
                    incidents.append(original)
                    present.add(original_id)
    ids = [i.id for i in incidents]

    campaigns: dict[str, str] = {}
    if ids:
        with intel.connection() as c:
            # Same notion of a campaign as the dashboard: 2+ reports, not all rejected
            rows = c.execute(
                """SELECT j.value AS incident_id, t.campaign_id FROM threat_reports t, json_each(t.incident_ids) j
                   WHERE t.campaign_id IN (SELECT campaign_id FROM threat_reports GROUP BY campaign_id
                                           HAVING count(*) > 1 AND sum(verdict_status != 'false_positive') > 0)
                     AND t.verdict_status != 'false_positive'
                     AND j.value IN (SELECT value FROM json_each(?))""",
                (json.dumps(ids),),
            ).fetchall()
        campaigns = {r["incident_id"]: r["campaign_id"] for r in rows}
        # A campaign with a single incident on the map is an orphan node that links nothing
        members: dict[str, set[str]] = {}
        for incident_id, campaign in campaigns.items():
            members.setdefault(campaign, set()).add(incident_id)
        campaigns = {i: c for i, c in campaigns.items() if len(members[c]) > 1}

    g = GraphBuilder(max_nodes)
    # Incidents first, so the limit never drops an incident while keeping its neighbours
    for inc in incidents:
        g.node("incident", inc.id, inc.title or inc.id, risk_score=inc.risk_score, module_id=inc.module_id,
               status=inc.status, source_url=inc.source_url)
    known = set(g.nodes)

    for inc in incidents:
        inc_node = f"incident:{inc.id}"
        if inc_node not in known:
            continue
        own_domain = domain_of(inc.source_url)
        if own_domain:
            g.edge(inc_node, g.node("domain", own_domain, own_domain), "published_on")
        if inc.promoter_name and inc.promoter_name.strip().casefold() not in UNKNOWN_ENTITIES:
            name = inc.promoter_name.strip()
            g.edge(g.node("promoter", name.casefold(), name), inc_node, "promotes")
        entity = (inc.entity_name or "").strip()
        # The pipeline falls back to the page title / URL when no firm is identified: not an entity
        if entity.casefold() not in UNKNOWN_ENTITIES and entity != (inc.title or "").strip() and "://" not in entity:
            name = inc.entity_name.strip()
            g.edge(inc_node, g.node("entity", name.casefold(), name, registry_status=inc.knf_registry_status),
                   "advertises")
        artifact = db.read_artifact(inc.storage_key) or {}
        extracted = artifact.get("extracted") if isinstance(artifact.get("extracted"), dict) else {}
        links = [u for key in ("resolved_links", "outbound_links") for u in (extracted.get(key) or []) if isinstance(u, str)]
        seen_targets: set[str] = set()
        for url in links[:40]:
            target = domain_of(url)
            if target and target != own_domain and target not in platforms and target not in seen_targets:
                seen_targets.add(target)
                g.edge(inc_node, g.node("link_domain", target, target), "links_to")
            for code in referral_codes(url):
                g.edge(inc_node, g.node("referral_code", code.casefold(), code), "uses_code")
        for rule in inc.violated_rules:
            if rule.rule_id == "CAMPAIGN_CLONE_MATCH":
                for original_id in clone_originals(rule):
                    if f"incident:{original_id}" in known:
                        g.edge(inc_node, f"incident:{original_id}", "clone_of")
            elif rule.rule_id == "KNF_WARNING_LIST_MATCH":
                g.edge(inc_node, g.node("warning_list", "knf", "Lista Ostrzeżeń Publicznych KNF"), "on_warning_list")
        if inc.id in campaigns:
            campaign = campaigns[inc.id]
            g.edge(inc_node, g.node("campaign", campaign, f"Kampania {campaign[:8]}"), "in_campaign")

    # Hide satellites that connect a single incident and carry no extra signal (keeps the map readable)
    degree: dict[str, int] = {}
    for source, target, _ in g.edges:
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1
    informative = {"warning_list", "entity", "promoter", "campaign"}
    keep = {
        node_id for node_id, node in g.nodes.items()
        if node["type"] == "incident" or node["type"] in informative or degree.get(node_id, 0) > 1
    }
    edges = [e for (s, t, _), e in g.edges.items() if s in keep and t in keep]
    return {"nodes": [n for k, n in g.nodes.items() if k in keep], "edges": edges, "truncated": g.truncated}
