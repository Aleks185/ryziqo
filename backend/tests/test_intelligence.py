import base64
import io
import time

from PIL import Image, ImageDraw
from tests.test_api import _build_test_client
from app.threat_intel import image_signature


def test_confirmed_report_bypasses_queue_and_force_bypasses_cache(tmp_path, monkeypatch):
    with _build_test_client(tmp_path) as client:
        api="/api/v1"
        body={"content":"Wpłać 950 PLN i odbierz gwarantowane 9000 PLN w 7 dni!", "module_ids":[2],"source_channel":"analyst_panel"}
        first=client.post(api+"/analyze/text",json=body).json()["report"]
        path=api+"/intelligence/reports/"+first["report_id"]
        assert client.patch(path,json={"verdict_status":"confirmed_fake","analyst_notes":"Sprawdzono"}).status_code==200
        with monkeypatch.context() as m:
            def forbidden(*a,**kw):
                raise AssertionError("Fast-path touched inference or queue")
            m.setattr(client.app.state.ollama,"check_health",forbidden)
            m.setattr(client.app.state.analysis_queue,"submit",forbidden)
            start=time.perf_counter()
            res=client.post(api+"/analyze/text",json={**body,"source_channel":"public_form"})
            print("fast text ms",round((time.perf_counter()-start)*1000,2))
            hit=res.json()["report"]
            assert hit["result_origin"]=="fast_path" and hit["report_id"]!=first["report_id"]
        again=client.post(api+"/analyze/text",json={**body,"force_full":True}).json()["report"]
        assert again["result_origin"]=="rules"
        rows=client.get(api+"/intelligence/reports",params={"q":"950 PLN"}).json()["items"]
        assert len({r["campaign_id"] for r in rows})==1
        group=rows[0]["campaign_id"]
        assert client.patch(api+"/intelligence/campaigns/"+group,json={"verdict_status":"false_positive"}).json()["updated"]>=3
        assert client.get(path).json()["verdict_status"]=="false_positive"
        assert client.get(api+"/intelligence/diagnostics").json()["fast_hits"]==1


def test_screenshot_hash_survives_recompression():
    img=Image.new("RGB",(640,320),"white")
    draw=ImageDraw.Draw(img)
    draw.rectangle((80,40,420,110),fill="black")
    draw.ellipse((40,150,250,290),fill="blue")
    draw.text((90,210),"PLN 950",fill="red")
    def signature(image,fmt):
        buf=io.BytesIO(); image.save(buf,fmt)
        return image_signature(base64.b64encode(buf.getvalue()).decode())
    a,b=signature(img,"PNG"),signature(img.crop((2,1,639,320)),"JPEG")
    assert a[0]!=b[0] and (int(a[1],16)^int(b[1],16)).bit_count()<=6


def test_rate_limit_and_untrusted_forwarding(tmp_path):
    with _build_test_client(tmp_path) as client:
        client.app.state.settings.report_limit_per_minute=1
        body={"content":"Tekst kontrolny dla analizy ryzyka inwestycyjnego.","module_ids":[1]}
        assert client.post("/api/v1/analyze/text",json=body,headers={"X-Forwarded-For":"192.0.2.1"}).status_code==200
        assert client.post("/api/v1/analyze/text",json=body,headers={"X-Forwarded-For":"192.0.2.2"}).status_code==429


def test_shared_domain_alone_does_not_reuse_confirmed_verdict(tmp_path):
    with _build_test_client(tmp_path) as client:
        api="/api/v1"
        scam={"content":"Wpłać 950 PLN, zysk 9000 PLN gwarantowany! https://www.knf.gov.pl/komunikat","module_ids":[2]}
        first=client.post(api+"/analyze/text",json=scam).json()["report"]
        assert client.patch(api+"/intelligence/reports/"+first["report_id"],
                            json={"verdict_status":"confirmed_fake"}).status_code==200
        other={"content":"Komunikat urzędu o nowych zasadach nadzoru: https://www.knf.gov.pl/inny","module_ids":[2]}
        hit=client.post(api+"/analyze/text",json=other).json()["report"]
        assert hit["result_origin"]!="fast_path"


def test_shared_server_ip_does_not_merge_campaigns():
    from app.threat_intel import Intelligence
    where,args=Intelligence.relation({"target_server_ip":"104.16.0.1","canonical_domain":"facebook.com",
                                      "target_url":None})
    assert where=="(0)" and args==[]
    where,args=Intelligence.relation({"target_server_ip":"104.16.0.1"},"context")
    assert args==["104.16.0.1"]
