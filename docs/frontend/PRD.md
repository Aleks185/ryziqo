> **Dokument historyczny** — notatki z etapu prototypowania frontendu w Emergent (przeniesione z `frontend/`). Aktualny opis: [frontend-architecture.md](../frontend-architecture.md); obowiązujący kontrakt: [CONTRACT.md](../../CONTRACT.md).

# INVESTWATCH — PRD

## Problem statement
"zacznij pracę podejdz krytycznie do całości i pytaj o grafikę i podobne" + HackNation brief (hacknation krzysztof.md). Frontend panel for UKNF analysts that detects problematic investment ads, finfluencers and shadow advisory (Modules M1/M2/M3). Emergent builds the frontend and the API contract draft. Krzysztof works on the frontend. Aleks builds the backend (FastAPI + SQLite + scraper + Ollama).

## Architecture
- React (CRA in the Emergent preview, can be moved to Vite later), Tailwind, Recharts, native WebSocket, sonner.
- One configurable API address: REACT_APP_INVESTWATCH_API_URL (default http://localhost:8000/api/v1). The WS address is derived from it: /ws/alerts.
- DEMO mode: a rule-based engine in the browser (src/lib/demoEngine.js) that follows the contract and stores data in localStorage. When the page is HTTPS and the API is HTTP, the app does not probe the API, so the console stays clean.
- CONTRACT.md (w katalogu głównym repo, zamrożony v1.0.0): data models, REST endpoints, WS events and the AI-Driven Development Workflow.

## Implemented (2026-06)
- Dashboard: module filter, KPIs built only from saved incidents, 14-day trend, incident register, compact live log
- Analysis form: Text/URL/Image tabs (URL and OCR are disabled in DEMO), 6 fictional samples with ground_truth, module choice, all form states
- Incident detail: score, per-module scores, reasoning, verbatim quotes with highlighting, entity/registry info (not checked in DEMO), SHA-256 hash, status, reference label, A4 print with a signature area
- Calibration: threshold slider, TP/FP/FN/TN matrix, precision/recall/F1, FP/FN vs threshold chart
- Live Crawler Log page; toast when risk ≥ 0.70 (no duplicates); PL/EN; DEMO banner with a retry button; SVG logo
- Fixes from testing: running the samples twice no longer creates duplicates; the disclaimer has DEMO wording; text no longer breaks mid-word

## Backlog
- P0: connect Aleks's backend and freeze the contract; multi-stage Dockerfile for docker-compose
- P1: set <html lang> on start; keep the live log after a reload; mobile module filter; clipped label on the calibration chart
- P2: npm audit, materials for the PDF and the video
