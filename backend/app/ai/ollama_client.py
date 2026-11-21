"""Local on-premise Ollama inference client (zero external paid APIs)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("investwatch.ollama")


class OllamaClient:
    """Connects to Ollama running natively on host (e.g. http://host.docker.internal:11434)."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.preferred_model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model
        self.timeout = settings.ollama_timeout_seconds
        self.active_model: str = settings.ollama_model
        self.is_available: bool = False

    async def check_health(self) -> bool:
        """Check whether Ollama is reachable and select an installed open-source model."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
                models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
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

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        """Request structured JSON output from Ollama; returns None on timeout/unavailable."""
        if not self.is_available:
            return None

        body = {
            "model": self.active_model,
            "system": system_prompt,
            "prompt": user_prompt[:3500],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 380},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=body)
                resp.raise_for_status()
                raw_text = resp.json().get("response", "")
                return self._parse_json_response(raw_text)
        except Exception as exc:
            logger.warning("Błąd inferencji Ollama (%s): %s", self.active_model, exc)
            return None

    async def embed_text(self, text: str) -> list[float] | None:
        """Optional local Ollama embeddings; falls back cleanly if model isn't pulled."""
        if not self.is_available:
            return None
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.embed_model, "prompt": text[:1500]},
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
