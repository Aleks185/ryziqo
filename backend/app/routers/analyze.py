"""Synchronous on-demand analysis of pasted text or a single public URL (CONTRACT.md v1.1.0)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

from fastapi.responses import StreamingResponse
from app.ai.vision_analyzer import VISION_SCHEMA, VISION_SYSTEM_PROMPT, VisionFindings
from app.analysis_queue import current_job, TERMINAL, status
from app.database import utc_now_iso
from app.threat_intel import input_meta, enrich_page, mask_personal_data
from app.ocr import read_text as ocr_read_text
from app.image_processor import normalize_screenshot
from app.models import AnalysisReport, AnalyzeResponse, AnalyzeScreenshotRequest, AnalyzeTextRequest, AnalyzeUrlRequest, WebSocketAlertEvent
from app.scraper.fetcher import build_manual_text_page
from app.scraper.ssrf import SSRFError, validate_authority, validate_public_url

logger = logging.getLogger("ryziqo.analyze")

router = APIRouter(prefix="/api/v1/analyze", tags=["analyze"])


def _unique_modules(module_ids: list[int]) -> list[int]:
    return sorted(set(module_ids))


async def _broadcast_complete(request: Request, source: str, incident_ids: list[str]) -> None:
    await request.app.state.ws_manager.broadcast(
        WebSocketAlertEvent(
            type="analysis_complete",
            timestamp=utc_now_iso(),
            stage="completed",
            source=source,
            message=f"Zakończono analizę na żądanie: {source} (zapisano {len(incident_ids)} wyników).",
            extra={"incident_ids": incident_ids, "processed": 1, "incidents_saved": len(incident_ids)},
        )
    )


def _mode(request: Request) -> str:
    return "live" if request.app.state.ollama.is_available else "demo_fallback"


def cache_key(request, body, kind, payload):
    model = request.app.state.ollama
    options = body.model_dump(exclude={"content", "image_base64", "source_channel", "force_full", "platform",
                                       "share_mode", "reporter_display_name", "reporter_key"})
    options["module_ids"] = sorted(set(body.module_ids))
    parts = [kind, hashlib.sha256(payload.encode()).hexdigest(), options, model.active_model,
             model.vision_model_override, model.vision_enabled, model.is_available, "prompt-pl-v4", "preprocess-v3"]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def lookup(db, key):
    raw = db.cached_response(key, time.time())
    if not raw:
        return None
    response = AnalyzeResponse.model_validate_json(raw)
    current = [db.get_incident(item.id) for item in response.items]
    if not all(a and a.content_hash == b.content_hash and a.risk_score == b.risk_score and a.model_used == b.model_used
               for a, b in zip(current, response.items)):
        return None
    response.items = current
    current_job.get().metrics["cache_hit"] = True
    return response


def finish(request, items, kind, key, cache=True, extra_limitations=()):
    score = round(max((item.risk_score for item in items), default=0) * 100)
    findings = []
    summaries = []
    for item in items:
        quotes = [q for q in item.evidence_quotes if not q.startswith("[") or q.startswith("[VLM]")]
        descriptions = [r.reason for r in item.violated_rules]
        findings.append({"module_id": item.module_id, "reasons": descriptions, "evidence": quotes})
        summaries.extend(q[5:] for q in item.evidence_quotes if q.startswith("[AI] "))
    summary = " ".join(dict.fromkeys(summaries)) or f"Ocena ryzyka materiału wynosi {score}/100."
    limitations = ["Wynik wspomaga ocenę analityka i wymaga weryfikacji źródła.", *extra_limitations]
    fallback = [str(item.module_id) for item in items if item.is_demo_fallback]
    if fallback:
        limitations.append("Ocena na podstawie reguł w modułach: " + ", ".join(fallback) + ".")
    report = AnalysisReport(source_type=kind, risk_score=score, findings=findings,
                            summary=summary,
                            limitations=limitations)
    response = AnalyzeResponse(items=items, mode=_mode(request), report=report)
    if cache and items and (response.mode == "demo_fallback" or any(not i.is_demo_fallback for i in items)):
        now = time.time()
        request.app.state.db.cache_response(key, response.model_dump_json(), now + (900 if kind == "url" else 86400), now)
    return response


async def dispatch(request, body):
    intel = request.app.state.intel
    queue = request.app.state.analysis_queue
    started = time.monotonic()
    identity = await asyncio.to_thread(intel.identity, request, body)
    persist = body.persist
    if body.source_channel == "public_form" and getattr(body, "content", None):
        body.content = mask_personal_data(body.content)
    is_url = isinstance(body, AnalyzeUrlRequest)
    if is_url:
        try:
            validate_authority(body.url)
        except SSRFError as exc:
            raise HTTPException(400,str(exc)) from exc
    # The semaphore only bounds CPU-heavy signature work (image decoding / pHash); network fetches
    # happen inside the analysis queue, so slow pages cannot block unrelated text submissions.
    async with request.app.state.signature_slots:
        meta = {**await asyncio.to_thread(input_meta, body), **identity}

    def known():
        if body.force_full:
            return None
        match, count = intel.confirmed(meta)
        if match is None:
            return None
        response = AnalyzeResponse.model_validate_json(match["response_json"])
        previous_summary = response.report.summary
        response.report.source_type = meta["source_type"]
        response.report.summary = f"Dopasowano do potwierdzonego zagrożenia w bazie zgłoszeń (liczba wcześniejszych zgłoszeń: {count}). {previous_summary}"
        if not persist:
            response.report.result_origin = "fast_path"
            return response
        return intel.save(meta, body, response, "fast_path", time.monotonic()-started, match)

    hit = await asyncio.to_thread(known)
    if hit:
        return queue.completed(hit)

    async def operation():
        job = current_job.get()
        job.force_full = body.force_full
        start = time.monotonic()
        if is_url:
            status("fetching")
            page = await fetch_url(request, body)
            request.state.fetched_page = page
            await asyncio.to_thread(enrich_page, meta, page, request.app.state.settings)
            hit = await asyncio.to_thread(known)
            if hit:
                return hit
        job.history = await asyncio.to_thread(intel.context, meta)
        fn = run_url if is_url else run_text
        response = await fn(request, body, persist)
        origin = ("cache" if job.metrics["cache_hit"] else
                  "ollama" if any(not i.is_demo_fallback for i in response.items) else "rules")
        if not persist:
            response.report.result_origin = origin
            return response
        if not meta["excerpt"] and response.items:
            meta["excerpt"] = response.items[0].content_excerpt
        return await asyncio.to_thread(intel.save, meta, body, response, origin, time.monotonic()-start)
    return queue.submit(operation)


def get_job(request, job_id):
    job = request.app.state.analysis_queue.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Zadanie wygasło lub nie istnieje.")
    return job


@router.post("/jobs", status_code=202)
async def submit_job(request: Request, body: AnalyzeTextRequest | AnalyzeScreenshotRequest | AnalyzeUrlRequest):
    job = await dispatch(request, body)
    if job.result is not None:
        return {"job_id":job.id,"result":job.result.model_dump(mode="json")}
    return {"job_id": job.id}


@router.delete("/jobs/{job_id}")
async def cancel_job(request: Request, job_id: str):
    job = get_job(request, job_id)
    job.cancel()
    return {"status": job.stage}


@router.get("/jobs/{job_id}/events")
async def events(request: Request, job_id: str):
    job = get_job(request, job_id)
    try:
        start = max(0, int(request.headers.get("last-event-id", "0") or 0))
    except ValueError:
        raise HTTPException(400, "Nieprawidłowy identyfikator zdarzenia.")

    async def stream():
        cursor = start
        while True:
            job.changed.clear()
            for sequence, event, value in list(job.events):
                if sequence > cursor:
                    yield f"id: {sequence}\nevent: {event}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"
                    cursor = sequence
            if (job.stage in TERMINAL and cursor >= job.sequence) or await request.is_disconnected():
                break
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=10)
            except TimeoutError:
                yield ": keepalive\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/text", response_model=AnalyzeResponse)
async def analyze_text(request: Request, body: AnalyzeTextRequest | AnalyzeScreenshotRequest) -> AnalyzeResponse:
    job = await dispatch(request, body)
    await job.task
    if job.error:
        raise job.error
    if job.result is None:
        raise HTTPException(409, "Anulowano analizę.")
    return job.result


async def run_text(request: Request, body: AnalyzeTextRequest | AnalyzeScreenshotRequest, persist: bool = True) -> AnalyzeResponse:
    """Analyze pasted text (ad copy, post, video description) with Modules 1–3."""
    worker = request.app.state.worker
    db = request.app.state.db

    await request.app.state.ollama.check_health()
    kind = "screenshot" if isinstance(body, AnalyzeScreenshotRequest) else "text"
    key = cache_key(request, body, kind, body.image_base64 if kind == "screenshot" else body.content)
    cached = None if body.force_full or not persist else lookup(db, key)
    if cached:
        if isinstance(body, AnalyzeTextRequest) and body.ground_truth_label is not None:
            for item in cached.items:
                if item.ground_truth_label != body.ground_truth_label:
                    db.update_incident_label(item.id, body.ground_truth_label)
                    item.ground_truth_label = body.ground_truth_label
        await _broadcast_complete(request, cached.items[0].source_url, [i.id for i in cached.items])
        return cached
    status("preprocessing")
    limitations: list[str] = []
    if isinstance(body, AnalyzeScreenshotRequest):
        image = await normalize_screenshot(body.image_base64)
        current_job.get().metrics["preprocessing_s"] += time.monotonic() - current_job.get().updated
        reading = await request.app.state.ollama.generate_vision_json(
            VISION_SYSTEM_PROMPT,
            "Przepisz dosłownie czytelną treść w języku źródła, w tym kwoty, ostrzeżenia i drobny druk. "
            "Jeśli treści nie da się odczytać, zwróć pusty tekst. Nie uzupełniaj brakujących słów.",
            [image],
            {"type": "object", "properties": {"text": {"type": "string"}, **VISION_SCHEMA["properties"]},
             "required": ["text", *VISION_SCHEMA["required"]]},
        )
        pixels = base64.b64decode(image)
        if reading is None:
            # Local OCR fallback: the text is read, but logos / visual endorsement are not assessed
            ocr_text = await asyncio.to_thread(ocr_read_text, pixels)
            if ocr_text is None:
                raise HTTPException(503, "Model wizyjny jest niedostępny.")
            reading = {"text": ocr_text}
            limitations.append("Odczyt lokalnym OCR bez modelu wizyjnego: logotypy i grafiki nie były oceniane.")
        content = reading.get("text")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(422, "Nie udało się odczytać reklamy z obrazu.")
        if body.source_channel == "public_form":
            content = mask_personal_data(content)
        digest = hashlib.sha256(pixels).hexdigest()
        page = build_manual_text_page(content, body.title, "manual://screenshot/" + digest)
        page.screenshots = [pixels]
        if not limitations:
            page.vision_findings = VisionFindings.model_validate(reading).model_dump()
    else:
        page = build_manual_text_page(body.content, body.title, body.source_url)
    items = await worker.analyze_page(page, _unique_modules(body.module_ids), persist=persist)
    if not persist:
        return finish(request, items, kind, key, cache=False, extra_limitations=limitations)

    if isinstance(body, AnalyzeTextRequest) and body.ground_truth_label is not None:
        for inc in items:
            db.update_incident_label(inc.id, body.ground_truth_label)
        items = [db.get_incident(inc.id) or inc for inc in items]

    await _broadcast_complete(request, page.source_url, [i.id for i in items])
    return finish(request, items, kind, key, extra_limitations=limitations)


@router.post("/url", response_model=AnalyzeResponse)
async def analyze_url(request: Request, body: AnalyzeUrlRequest) -> AnalyzeResponse:
    job = await dispatch(request, body)
    await job.task
    if job.error:
        raise job.error
    if job.result is None:
        raise HTTPException(409, "Anulowano analizę.")
    return job.result


async def run_url(request: Request, body: AnalyzeUrlRequest, persist: bool = True) -> AnalyzeResponse:
    """Analyze the page fetched by `dispatch` (anti-SSRF, size/redirect limits applied by the fetcher)."""
    worker = request.app.state.worker
    page = request.state.fetched_page
    await request.app.state.ollama.check_health()
    status("preprocessing")
    key = cache_key(request, body, "url", json.dumps([page.final_url, page.payload_sha256, page.raw_html,
                      [hashlib.sha256(s).hexdigest() for s in page.screenshots or []]]))
    cached = None if body.force_full or not persist else lookup(request.app.state.db, key)
    if cached:
        await _broadcast_complete(request, page.source_url, [i.id for i in cached.items])
        return cached
    items = await worker.analyze_page(page, _unique_modules(body.module_ids), persist=persist)
    if not persist:
        return finish(request, items, "url", key, cache=False)
    await _broadcast_complete(request, page.source_url, [i.id for i in items])
    return finish(request, items, "url", key)


async def fetch_url(request, body):
    fetcher = request.app.state.fetcher

    try:
        page = await fetcher.fetch_public_url(body.url, use_playwright=body.use_playwright)
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise HTTPException(504, "Upłynął czas pobierania strony.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Strona zwróciła HTTP {exc.response.status_code}.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Nie udało się pobrać %s: %s", body.url, exc)
        raise HTTPException(status_code=502, detail=f"Nie udało się pobrać strony: {exc}") from exc

    return page
