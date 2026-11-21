from tests.test_api import _build_test_client


def test_demo_dossier_and_live_event(tmp_path):
    with _build_test_client(tmp_path) as api:
        for _ in range(2):
            assert api.post("/api/system/seed-demo").json() == {"reports_count":14,"active_campaigns":3}
        assert api.get("/api/dashboard/stats").json() == dict(active_campaigns=3,unreviewed_reports=9,
                                                               monitored_ips=5,noise_reduction_percent=86)
        groups = api.get("/api/campaigns").json()
        assert [g["reports_count"] for g in groups] == [5,4,3]
        path = "/api/campaigns/camp-185-220-101-45"
        case = api.get(path).json()
        profile = case["actor_profile"]
        assert len(profile["domains"])==3 and len(profile["phones"])==2 and len(profile["bank_accounts"])==1
        assert len(case["notes"])==2 and len(case["timeline"])==5
        nodes = {n["id"] for n in case["graph"]["nodes"]}
        assert all(e["source"] in nodes and e["target"] in nodes for e in case["graph"]["edges"])
        note = api.post(path+"/notes",json={"content":"  Sprawdzono  "}).json()
        assert note["content"]=="Sprawdzono" and note["author"]=="Analityk Nadzoru"
        assert api.delete("/api/campaigns/other/notes/"+note["id"]).status_code==404
        assert api.delete(path+"/notes/"+note["id"]).status_code==204
        with api.websocket_connect("/ws/alerts") as ws:
            assert ws.receive_json()["type"]=="connected"
            response=api.post("/api/system/simulate-attack")
            assert response.status_code==201
            event=ws.receive_json()
            assert event["type"]=="NEW_REPORT" and event["campaignId"]==case["id"]
            assert event["reportId"]==response.json()["report"]["id"]
        assert api.get(path).json()["reports_count"]==6
    with _build_test_client(tmp_path) as api:
        assert len(api.get("/api/reports").json())==15


def test_report_entry_review_and_filters(tmp_path):
    with _build_test_client(tmp_path) as api:
        body=dict(title="ŻÓŁTA reklama",content="Kontakt test.example +48 22 100 20 30 PL61 1090 1014 0000 0712 1981 2874",
                  ip_address="2001:db8::1",source="CITIZEN_FORM",risk_score=90)
        response=api.post("/api/reports",json=body)
        assert response.status_code==201
        row=response.json()
        assert row["domain"]=="test.example" and row["artifacts"]["phones"]==["+48 22 100 20 30"]
        assert row["artifacts"]["bank_accounts"]==["PL61 1090 1014 0000 0712 1981 2874"]
        filters=dict(q="żółta",reviewed="false",source="CITIZEN_FORM",minRisk=88,maxRisk=91)
        assert api.get("/api/reports",params=filters).json()==[row]
        path="/api/reports/"+row["id"]+"/review"
        assert api.patch(path,json={"human_reviewed":True}).json()["human_reviewed"]
        assert api.get("/api/reports",params=filters).json()==[]
        assert not api.patch(path).json()["human_reviewed"]
        assert api.get("/api/campaigns/camp-2001_db8__1").json()["reports_count"]==1
        assert api.get("/api/campaigns/unknown").status_code==404
        assert api.post("/api/reports",json={**body,"ip_address":"invalid"}).status_code==422
        assert api.post("/api/reports",json={**body,"ip_address":"::1"}).json()["ip_address"]=="192.0.2.1"

