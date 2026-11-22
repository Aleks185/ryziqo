from datetime import datetime, timezone

from app import osint
from tests.test_api import _build_test_client

RDAP_PL = {
    "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "home.pl S.A."]]]}],
    "events": [{"eventAction": "registration", "eventDate": "2026-11-18T10:00:00Z"}],
    "nameservers": [{"ldhName": "NS1.home.pl."}, {"ldhName": "ns2.home.pl"}],
}


def test_parse_rdap_registrar_age_and_nameservers():
    out = osint.parse_rdap(RDAP_PL, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert out == {"registrar": "home.pl S.A.", "domain_created_at": "2026-11-18", "domain_age_days": 4,
                   "nameservers": ["ns1.home.pl", "ns2.home.pl"]}


def test_enrichment_degrades_gracefully_when_sources_are_down(monkeypatch):
    monkeypatch.setattr(osint, "follow_redirects", lambda url, t: ([url, "https://vectra.example.pl/x"], None))
    monkeypatch.setattr(osint, "resolve_ipv4", lambda host: None)
    monkeypatch.setattr(osint, "lookup_rdap", lambda host, t: {})
    info = osint.enrich_url_infrastructure("https://short.example/abc")
    assert info["redirect_chain"][-1] == "https://vectra.example.pl/x"
    assert {"dns", "rdap"} <= set(info["errors"]) and info["fresh_domain"] is False
    assert osint.enrich_url_infrastructure("not a url")["errors"] == ["invalid_url"]


def test_campaign_detail_enrich_and_graph_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(osint, "enrich_url_infrastructure", lambda url, timeout=3.5: {
        "redirect_chain": [url, "https://vectra-trade.pl/start"], "target_server_ip": "5.9.1.2", "hosting_org": "Hetzner Online GmbH",
        "hosting_asn": "AS24940", "hosting_country": "Germany", "registrar": "OVH", "domain_age_days": 4,
        "domain_created_at": "2026-11-18", "nameservers": ["ns1.ovh.net"], "errors": []})
    with _build_test_client(tmp_path) as client:
        api = "/api/v1"
        client.post(api + "/analyze/text", json={"content": "Sygnały CFD gwarantowany zysk 900% https://vectra-trade.pl/start", "module_ids": [2]})
        client.post(api + "/analyze/text", json={"content": "Wpłać 950 PLN, gwarantowany zysk https://vectra-trade.pl/start", "module_ids": [2]})
        group = client.get(api + "/intelligence/reports").json()["items"][0]["campaign_id"]
        res = client.post(f"{api}/intelligence/campaigns/{group}/enrich")
        assert res.status_code == 200 and res.json()["enriched"] >= 1
        detail = client.get(f"{api}/intelligence/campaigns/{group}").json()
        r = detail["reports"][0]
        assert r["hosting_org"] == "Hetzner Online GmbH" and r["registrar"] == "OVH" and r["nameservers"] == ["ns1.ovh.net"]
        assert r["redirect_chain"][-1] == "https://vectra-trade.pl/start" and "reporter_ip" not in r
        graph = {"nodes": [{"id": "c1", "type": "social", "label": "@vectra_vip", "note": "kanał"}],
                 "edges": [{"id": "e1", "source": "c1", "target": "campaign:" + group, "label": "promuje"}],
                 "positions": {"c1": {"x": 10, "y": 20}}, "hidden": []}
        assert client.put(f"{api}/intelligence/campaigns/{group}/graph", json=graph).status_code == 200
        assert client.get(f"{api}/intelligence/campaigns/{group}").json()["graph"]["nodes"][0]["label"] == "@vectra_vip"
        assert client.post(f"{api}/intelligence/campaigns/nope/enrich").status_code == 404


def test_campaign_detail_carries_decision_and_dissolve(tmp_path):
    with _build_test_client(tmp_path) as client:
        api = "/api/v1/intelligence"
        for text in ("Sygnały CFD gwarantowany zysk 900% https://vectra-trade.pl/start", "Wpłać 950 PLN, gwarantowany zysk https://vectra-trade.pl/start"):
            client.post("/api/v1/analyze/text", json={"content": text, "module_ids": [2]})
        group = client.get(api + "/reports").json()["items"][0]["campaign_id"]
        assert client.get(f"{api}/campaigns/{group}").json()["classification"] == "pending"
        body = {"classification": "confirmed", "description": "ten sam schemat"}
        assert client.put(f"{api}/campaigns/{group}/decision", json=body).status_code == 200
        detail = client.get(f"{api}/campaigns/{group}").json()
        assert (detail["classification"], detail["description"]) == ("confirmed", "ten sam schemat")
        assert client.delete(f"{api}/campaigns/{group}").json()["detached"] >= 2
        assert client.get(f"{api}/campaigns/{group}").status_code == 404
