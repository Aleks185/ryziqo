import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.analysis_queue import AnalysisQueue
from app.models import AnalyzeResponse
from tests.test_api import _build_test_client


@pytest.mark.anyio
async def test_fifo_capacity_and_cancel():
    queue = AnalysisQueue()
    gate = asyncio.Event()
    order = []

    async def operation(index):
        order.append(index)
        await gate.wait()
        return AnalyzeResponse(items=[], mode="live")

    jobs = [queue.submit(lambda i=i: operation(i)) for i in range(9)]
    await asyncio.sleep(0)
    assert order == [0]
    with pytest.raises(HTTPException) as full:
        queue.submit(lambda: operation(9))
    assert full.value.status_code == 429
    jobs[4].cancel()
    jobs.append(queue.submit(lambda: operation(9)))
    gate.set()
    await asyncio.gather(*(j.task for j in jobs), return_exceptions=True)
    assert order == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    assert jobs[4].stage == "cancelled"
    assert all(j.stage == "completed" for j in jobs if j is not jobs[4])


@pytest.mark.parametrize("upstream,expected", [(403, 502), (408, 504)])
def test_fetch_failure_has_no_verdict(tmp_path, upstream, expected):
    async def fail(*args, **kwargs):
        req = httpx.Request("GET", "https://1.1.1.1/")
        if upstream == 408:
            raise httpx.ReadTimeout("timeout", request=req)
        raise httpx.HTTPStatusError("forbidden", request=req, response=httpx.Response(403))

    with _build_test_client(tmp_path) as client:
        client.app.state.fetcher.fetch_public_url = fail
        response = client.post("/api/v1/analyze/url", json={"url": "https://1.1.1.1/"})
        assert response.status_code == expected and "items" not in response.json()


def test_sse_replay_cache_and_label(tmp_path):
    with _build_test_client(tmp_path) as client:
        url = "/api/v1/analyze/jobs"
        payload = {"content": "Gwarantowany zysk 400 procent w 48 godzin!", "module_ids": [2]}
        for hit in [False, True]:
            job_id = client.post(url, json=payload).json()["job_id"]
            events = client.get(f"{url}/{job_id}/events")
            assert "event: queued" in events.text and "event: completed" in events.text
            job = client.app.state.analysis_queue.jobs[job_id]
            assert job.metrics["cache_hit"] is hit
            assert job.result.report.requires_human_review
            assert 0 <= job.result.report.risk_score <= 100
            tail = client.get(f"{url}/{job_id}/events", headers={"Last-Event-ID": str(job.sequence-1)})
            assert "event: completed" in tail.text and "event: queued" not in tail.text

@pytest.mark.anyio
async def test_url_revalidates_strong_etag(monkeypatch):
    from app.config import Settings
    from app.scraper import fetcher
    seen = []

    def serve(req):
        seen.append(req.headers.get("if-none-match"))
        if len(seen) == 2:
            return httpx.Response(304)
        return httpx.Response(200, text="<p>Oferta</p>", headers={"content-type": "text/html", "etag": '"v1"'})

    client = httpx.AsyncClient
    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(serve), **kw))
    reader = fetcher.PageFetcher(Settings(crawler_rate_limit_seconds=0, crawler_use_playwright_fallback=False))
    first = await reader.fetch_public_url("https://1.1.1.1/")
    second = await reader.fetch_public_url("https://1.1.1.1/")
    assert seen == [None, '"v1"']
    assert second.raw_html == first.raw_html and second.payload_sha256 == first.payload_sha256
