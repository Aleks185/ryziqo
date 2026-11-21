# #InvestWatch — System Monitoringu Treści Inwestycyjnych (UKNF)

Prototyp MVP (HackNation 2026) do automatycznej identyfikacji, agregacji i analizy materiałów promocyjnych oraz ofert finansowych w trzech modułach:
1. **Moduł 1** — Finfluencerzy i podmioty trzecie (reklamy polskich i zagranicznych firm inwestycyjnych).
2. **Moduł 2** — Weryfikacja zgodności i informacji o ryzyku (18 kryteriów MiFID II / rozp. del. 2017/565 + analiza DOM/CSS).
3. **Moduł 3** — Shadow Advisory (wykrywanie nieautoryzowanego doradztwa inwestycyjnego wg art. 76, 2 i 3 u.o.i.f.).

## Wymagania sprzętowe i środowiskowe

- **Docker + Docker Compose** (rekomendowany start on-premise)
- **RAM:** min. 4 GB (tryb z regułami/fallback), min. 8–16 GB przy lokalnym modelu LLM w Ollama
- **Opcjonalnie (lokalne AI on-premise):** [Ollama](https://ollama.com/) uruchomiona na hoście (`ollama pull gemma3:4b` lub `gemma4`) — zero płatnych zewnętrznych API
- **Do developmentu bez Dockera:** Python 3.11+ (backend), Node.js 20+ i Yarn 1.22 (frontend)

## Struktura repozytorium

```text
backend/         FastAPI + scraper anty-SSRF + Moduły AI 1–3 + SQLite (docs/backend-architecture.md)
frontend/        Panel analityka: React 19 + Tailwind, w Dockerze serwowany przez Nginx (docs/frontend-architecture.md)
data/            Reguły UKNF, snapshot rejestrów KNF, mock-strony demo, dane startowe
docs/            Dokumentacja architektury, bezpieczeństwa i procesu pracy z AI
CONTRACT.md      Zamrożony kontrakt REST + WebSocket między backendem a frontendem
```

## Quick Start (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

Po uruchomieniu:
- **Panel analityka (frontend):** `http://localhost:3000` (Nginx przekazuje `/api/` i `/ws/` do backendu)
- **API:** `http://localhost:8000/api/v1/health`
- **Swagger / OpenAPI:** `http://localhost:8000/docs`
- **WebSocket alertów:** `ws://localhost:8000/ws/alerts`
- **Podgląd lokalnych mock-stron demo:** `http://localhost:8000/mock-sites/broker_promo_hidden_risk.html`

## Quick Start (lokalnie bez Dockera)

**Backend** (port `8000`):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (port `3000`, hot-reload, łączy się z `http://localhost:8000/api/v1`):

```bash
cd frontend
cp .env.example .env
yarn install
yarn start
```

## Konfiguracja serwisów (`.env`)

Wszystkie parametry znajdują się w [.env.example](.env.example). Sekrety są izolowane wyłącznie w `.env` (ignorowanym przez Git).

| Zmienna | Domyślna wartość | Opis |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` (Docker: `http://host.docker.internal:11434`) | Adres lokalnej instancji Ollama na hoście |
| `OLLAMA_MODEL` | `gemma3:4b` | Darmowy model open-source do analizy semantycznej |
| `DATABASE_PATH` | `../data/investwatch.db` (Docker: `/data/investwatch.db`) | Ścieżka trwałej bazy SQLite |
| `OBJECT_STORE_DIR` | `../data/object_store` (Docker: `/data/object_store`) | Lokalny object storage surowych HTML i JSON |
| `CRAWLER_SCHEDULE_MINUTES` | `15` | Interwał harmonogramu APScheduler |
| `HIGH_RISK_ALERT_THRESHOLD` | `0.65` | Próg emisji alertów `high_risk_alert` na `/ws/alerts` (w Dockerze także próg alertów w panelu) |
| `FRONTEND_PORT` | `3000` | Port hosta, na którym Docker Compose wystawia panel |

Zmienne frontendu (`REACT_APP_INVESTWATCH_API_URL`, `REACT_APP_ALERT_THRESHOLD`) opisuje [frontend/.env.example](frontend/.env.example). Są wklejane do bundla w czasie builda — nie umieszczaj w nich sekretów.

## Testy i audyt bezpieczeństwa (Cybersec)

```bash
cd backend
pytest -q
pip-audit -r requirements.txt

cd ../frontend
yarn audit
```

Wyniki audytów i analiza wpływu: [docs/security-licenses.md](docs/security-licenses.md).

## Tryb demo i znane ograniczenia

- **Fallback bez Ollama:** jeżeli Ollama na hoście jest niedostępna, system automatycznie działa w trybie `demo_fallback` (silnik deterministyczny 18 reguł UKNF + analiza DOM/CSS + etykietowane dane startowe w SQLite).
- **Lokalny snapshot KNF:** `data/knf_registry_snapshot.json` zawiera udokumentowany lokalny snapshot rejestrów KNF (data w polu `snapshot_date`) wraz z fikcyjnymi podmiotami `[DEMO]` dla lokalnych mock-stron — nie zastępuje bieżącej weryfikacji statusu prawnego w KNF.
- **Wskaźnik `risk_score` (0.00–1.00):** służy analitykowi do priorytetyzacji i kalibracji progu FP/FN; nie stanowi wiążącego rozstrzygnięcia prawnego.
- **Frontend a kontrakt:** panel powstał na roboczej wersji kontraktu i wymaga dostosowania do zamrożonego `CONTRACT.md` (lista rozbieżności: [docs/frontend-architecture.md](docs/frontend-architecture.md#5-zgodność-z-contractmd--znane-rozbieżności)). Do tego czasu przy braku zgodnego backendu działa jawnie oznaczony tryb DEMO (heurystyka regułowa w przeglądarce, nie AI).
- **Kontrakt API:** pełna specyfikacja endpointów i zdarzeń WebSocket w [CONTRACT.md](CONTRACT.md).
