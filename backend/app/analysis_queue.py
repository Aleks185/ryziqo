"""Bounded FIFO for the single ASGI worker. Jobs expire after delivery or inactivity."""
import asyncio
import logging
import time
import uuid
from collections import deque
from contextvars import ContextVar

from fastapi import HTTPException

current_job = ContextVar("analysis_job", default=None)
TERMINAL = {"completed", "failed", "cancelled"}


def status(stage):
    job = current_job.get()
    if job:
        job.emit("status", stage)


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.stage = "pending"
        self.events = deque(maxlen=4096)
        self.sequence = 0
        self.changed = asyncio.Event()
        self.started = self.updated = time.monotonic()
        self.result = self.error = self.task = None
        self.metrics = {"queue_s": 0, "preprocessing_s": 0, "load_s": 0, "ttft_s": None, "cache_hit": False}
        self.emit("status", "pending")

    def emit(self, event, value):
        self.sequence += 1
        self.updated = time.monotonic()
        if event in {"status", "queued"}:
            self.stage = value
        self.events.append((self.sequence, event, value))
        self.changed.set()

    def cancel(self):
        if self.stage not in TERMINAL:
            self.task.cancel()
            self.emit("status", "cancelled")
            self.emit("error", "Anulowano analizę.")


class AnalysisQueue:
    def __init__(self):
        self.jobs = {}
        self.lock = asyncio.Lock()  # asyncio.Lock grants access to waiters in FIFO order

    def completed(self, result):
        self.prune()
        job = Job()
        job.result = result
        job.task = asyncio.get_running_loop().create_future()
        job.task.set_result(None)
        job.emit("status", "completed")
        job.emit("completed", result.model_dump(mode="json"))
        self.jobs[job.id] = job
        return job

    def prune(self):
        now = time.monotonic()
        self.jobs = {k: j for k, j in self.jobs.items() if j.stage not in TERMINAL or now-j.updated < 120}

    def submit(self, operation):
        self.prune()
        if sum(j.stage not in TERMINAL for j in self.jobs.values()) >= 9:
            raise HTTPException(429, "Kolejka analiz jest pełna. Spróbuj ponownie później.")
        job = Job()
        self.jobs[job.id] = job
        job.emit("queued", "queued")
        job.task = asyncio.create_task(self.run(job, operation))
        return job

    async def run(self, job, operation):
        mark = current_job.set(job)
        try:
            async with self.lock:
                job.metrics["queue_s"] = time.monotonic() - job.started
                async with asyncio.timeout(600):
                    job.result = await operation()
                job.emit("status", "completed")
                job.emit("completed", job.result.model_dump(mode="json"))
        except asyncio.CancelledError:
            if job.stage != "cancelled":
                job.emit("status", "cancelled")
                job.emit("error", "Anulowano analizę.")
        except Exception as exc:
            job.error = exc if isinstance(exc, HTTPException) else HTTPException(503, "Analiza nie powiodła się lub przekroczyła limit czasu.")
            if isinstance(exc, HTTPException):
                logging.getLogger(__name__).info("Analysis %s: %s", job.id, exc.detail)
            else:
                logging.getLogger(__name__).exception("Analysis failed: %s", job.id)
            job.emit("status", "failed")
            job.emit("error", job.error.detail)
        finally:
            current_job.reset(mark)
            try:
                import resource
                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            except ImportError:
                peak = None
            job.metrics.update(total_s=time.monotonic()-job.started, backend_peak_kib=peak)
            logging.getLogger(__name__).info("analysis_metrics %s %s", job.id, job.metrics)

    async def close(self):
        for job in self.jobs.values():
            job.cancel()
        await asyncio.gather(*(j.task for j in self.jobs.values()), return_exceptions=True)
