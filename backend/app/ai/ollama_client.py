"""Local on-premise Ollama inference client (zero external paid APIs)."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from app.analysis_queue import current_job, status
import logging
import re
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("ryziqo.ollama")

VISION_FAMILIES = ("gemma3", "gemma4", "qwen2.5vl", "qwen2.5-vl", "llava", "llama3.2-vision", "minicpm-v")


class OllamaClient:
    """Connects to Ollama running natively on host (e.g. http://host.docker.internal:11434)."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.preferred_model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model
        self.inference_lock = asyncio.Lock()
        self.loaded_model = None
        self.num_thread = settings.ollama_num_thread
        self.timeout = settings.ollama_timeout_seconds
        self.num_predict = settings.ollama_num_predict
        self.num_ctx = settings.ollama_num_ctx
        self.keep_alive = settings.ollama_keep_alive
        self.vision_enabled = settings.ollama_vision_enabled
        self.vision_model_override = settings.ollama_vision_model.strip()
        self.active_model: str = settings.ollama_model
        self.installed_models: list[str] = []
        self.is_available: bool = False
        # Ollama < 0.5 rejects a JSON-schema "format"; remember it and fall back to "json"
        self._schema_format_supported: bool = True
        self._vision_capable: dict[str, bool] = {}

    async def check_health(self) -> bool:
        """Check whether Ollama is reachable and select an installed open-source model."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
                models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
                self.installed_models = models
                self.is_available = True
                if models:
                    if self.preferred_model in models:
                        self.active_model = self.preferred_model
                    else:
                        # Auto-pick preferred open-source family if exact tag differs
                        for family in ("gemma4", "gemma3", "gemma2", "qwen2.5", "llama3", "mistral"):
                            match = next((m for m in models if family in m.lower()), None)
                            if match:
                                self.active_model = match
                                break
                        else:
                            self.active_model = models[0]
                return True
        except Exception as exc:
            logger.info("Ollama niedostępna pod %s (%s) — aktywny tryb fallback.", self.base_url, exc)
            self.is_available = False
            return False

    def _options(self) -> dict[str, Any]:
        return {"num_thread": self.num_thread, "temperature": 0.1, "num_predict": self.num_predict, "num_ctx": self.num_ctx}

    async def _post_generate(self, body: dict[str, Any]) -> dict[str, Any] | None:
        async with self.session(body["model"]) as client:
            body.update(keep_alive=self.keep_alive, stream=True)
            for attempt in range(2):
                async with client.stream("POST", f"{self.base_url}/api/generate", json=body) as resp:
                    if attempt == 0 and resp.status_code in (400, 500) and isinstance(body["format"], dict):
                        if resp.status_code == 400:
                            self._schema_format_supported = False
                        body["format"] = "json"
                        continue
                    resp.raise_for_status()
                    parts = []
                    job = current_job.get()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        part = json.loads(line)
                        if part.get("error"):
                            raise ValueError("Ollama nie ukończyła analizy.")
                        if part.get("response"):
                            if not parts:
                                status("analyzing")
                            parts.append(part["response"])
                            if job:
                                if job.metrics["ttft_s"] is None:
                                    job.metrics["ttft_s"] = time.monotonic() - job.started
                                job.emit("token", part["response"])
                        if part.get("done"):
                            if job:
                                job.metrics["load_s"] += part.get("load_duration", 0) / 1e9
                                # total_duration covers model load + prompt eval + generation, not lock wait
                                job.metrics["llm_s"] += part.get("total_duration", 0) / 1e9
                            return self._parse_json_response("".join(parts))
        return None

    @asynccontextmanager
    async def session(self, model):
        status("queued")
        async with self.inference_lock:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if self.loaded_model and self.loaded_model != model:
                    unload = await client.post(f"{self.base_url}/api/generate",
                                               json={"model": self.loaded_model, "keep_alive": 0})
                    unload.raise_for_status()
                self.loaded_model = model
                status("loading_model")
                async with asyncio.timeout(self.timeout):
                    yield client

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Request structured JSON output from Ollama; returns None on timeout/unavailable.

        With `json_schema`, Ollama constrains decoding to the schema (structured outputs, Ollama >= 0.5).
        The caller is responsible for budgeting the prompt size (see app.ai.prompting).
        """
        if not self.is_available:
            return None

        fmt: dict[str, Any] | str = (
            json_schema if (json_schema and self._schema_format_supported) else "json"
        )
        body = {
            "model": self.active_model,
            "system": system_prompt,
            "prompt": user_prompt,
            "format": fmt,
            "stream": False,
            "options": self._options(),
        }
        try:
            return await self._post_generate(body)
        except Exception as exc:
            logger.warning("Błąd inferencji Ollama (%s): %s", self.active_model, exc)
            return None

    def vision_model(self) -> str | None:
        """Model used for screenshots: explicit override, else the active model if it is multimodal."""
        if self.vision_model_override:
            return self.vision_model_override
        if any(f in self.active_model.lower() for f in VISION_FAMILIES):
            return self.active_model
        return None

    async def supports_vision(self) -> bool:
        """True when vision is enabled and the chosen model reports the "vision" capability."""
        if not (self.is_available and self.vision_enabled):
            return False
        model = self.vision_model()
        if not model:
            return False
        if model in self._vision_capable:
            return self._vision_capable[model]
        capable = True  # older Ollama has no "capabilities" field: trust the family list
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{self.base_url}/api/show", json={"model": model})
                if resp.status_code == 200:
                    caps = resp.json().get("capabilities")
                    if isinstance(caps, list):
                        capable = "vision" in caps
                else:
                    capable = False
        except Exception:
            capable = False
        self._vision_capable[model] = capable
        return capable

    async def generate_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        images_b64: list[str],
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Multimodal (VLM) structured JSON request over base64 screenshots."""
        if not images_b64 or not await self.supports_vision():
            return None
        model = self.vision_model()
        body = {
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "images": images_b64,
            "format": json_schema if (json_schema and self._schema_format_supported) else "json",
            "stream": False,
            "options": self._options(),
        }
        try:
            return await self._post_generate(body)
        except Exception as exc:
            logger.warning("Błąd inferencji VLM Ollama (%s): %s", model, exc)
            return None

    async def embed_text(self, text: str) -> list[float] | None:
        """Optional local Ollama embeddings; falls back cleanly if model isn't pulled."""
        if not self.is_available:
            return None
        try:
            async with self.session(self.embed_model) as client:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.embed_model, "prompt": text[:1500], "keep_alive": self.keep_alive},
                )
                if resp.status_code != 200:
                    return None
                emb = resp.json().get("embedding")
                return [float(x) for x in emb] if isinstance(emb, list) and emb else None
        except Exception:
            return None

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any] | None:
        cleaned = raw.strip()
        if not cleaned:
            return None
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
