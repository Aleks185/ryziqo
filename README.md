# #InvestWatch — System Monitoringu Treści Inwestycyjnych (UKNF)

Prototyp MVP (HackNation 2026) do automatycznej identyfikacji, agregacji i analizy materiałów promocyjnych oraz ofert finansowych w trzech modułach:
1. **Moduł 1** — Finfluencerzy i podmioty trzecie (reklamy polskich i zagranicznych firm inwestycyjnych).
2. **Moduł 2** — Weryfikacja zgodności i informacji o ryzyku (18 kryteriów MiFID II / rozp. del. 2017/565 + analiza DOM/CSS).
3. **Moduł 3** — Shadow Advisory (wykrywanie nieautoryzowanego doradztwa inwestycyjnego wg art. 76, 2 i 3 u.o.i.f.).

## Wymagania sprzętowe i środowiskowe

- **Docker + Docker Compose** (rekomendowany start on-premise)
- **RAM:** min. 4 GB (tryb z regułami/fallback), min. 8–16 GB przy lokalnym modelu LLM w Ollama
- **Opcjonalnie (lokalne AI on-premise):** [Ollama](https://ollama.com/) na hoście (`ollama pull gemma3:4b` lub `gemma4`) albo w kontenerze (profil `ai`, poniżej) — zero płatnych zewnętrznych API
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

Z lokalnym AI w kontenerze (pobiera modele przy pierwszym starcie; w `.env` ustaw `OLLAMA_BASE_URL=http://ollama:11434`):

```bash
docker compose --profile ai up --build
```

Z automatycznym odkrywaniem nowych treści (lokalny SearXNG; w `.env` ustaw `DISCOVERY_ENABLED=true`):

```bash
docker compose --profile discovery up --build
```

Strony renderowane JavaScriptem: `INSTALL_PLAYWRIGHT=true` i `CRAWLER_USE_PLAYWRIGHT_FALLBACK=true` w `.env`, potem `docker compose build`.

Po uruchomieniu:
- **Panel analityka (frontend):** `http://localhost:3000` (Nginx przekazuje `/api/` i `/ws/` do backendu)
- **API:** `http://localhost:8000/api/v1/health`
- **Swagger / OpenAPI:** `http://localhost:8000/docs`
- **WebSocket alertów:** `ws://localhost:8000/ws/alerts`
- **Analiza na żądanie:** `POST /api/v1/analyze/text` i `POST /api/v1/analyze/url` (szczegóły w [CONTRACT.md](CONTRACT.md))
- **Discovery (SearXNG):** `POST /api/v1/discovery/run`, `GET /api/v1/discovery/recent`; **odświeżenie rejestru KNF:** `POST /api/v1/knf-registry/refresh?dry_run=true`
- **Okresowo skanowane źródła:** `/api/v1/watchlist` (startowa lista: `POST /api/v1/watchlist/seed`); **raporty modułów (JSON/CSV):** `/api/v1/reports/{1|2|3}?format=csv`
- **Podgląd lokalnych mock-stron demo:** `http://localhost:8000/mock-sites/broker_promo_hidden_risk.html`

## Quick Start (lokalnie bez Dockera)

**Backend** (port `8000`):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
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
| `CRAWLER_CRON` | puste | Wyrażenie crontab (UTC) zastępujące interwał, np. `*/30 * * * *` |
| `CRAWLER_PROXIES` | puste | Lista proxy rotowanych per żądanie (`http://...`, `socks5://...`) |
| `DEDUP_SIMILARITY_THRESHOLD` | `0.92` | Próg podobieństwa embeddingów przy ponownym skanie tego samego URL |
| `INSTALL_PLAYWRIGHT` | `false` | Build-arg Dockera: Chromium dla stron renderowanych JS |
| `CRAWLER_USE_PLAYWRIGHT_FALLBACK` | `false` | Renderuj w Chromium strony z małą ilością tekstu (SPA) |
| `CRAWLER_PLAYWRIGHT_MIN_TEXT_CHARS` | `400` | Próg widocznego tekstu uruchamiający render |
| `HIGH_RISK_ALERT_THRESHOLD` | `0.65` | Próg emisji alertów `high_risk_alert` na `/ws/alerts` (w Dockerze także próg alertów w panelu) |
| `FRONTEND_PORT` | `3000` | Port hosta, na którym Docker Compose wystawia panel |
| `OLLAMA_NUM_PREDICT` / `OLLAMA_NUM_CTX` | `768` / `8192` | Limit tokenów odpowiedzi LLM i okno kontekstu |
| `OLLAMA_VISION_ENABLED` | `false` | Analiza VLM zrzutów ekranu (wymaga Playwrighta i modelu z obsługą obrazów) |
| `AI_PROMPT_CONTENT_CHARS` | `9000` | Budżet znaków treści w prompcie (sekcje zamiast ucinania tekstu) |
| `AI_RAG_FEW_SHOT_ENABLED` | `true` | Dynamiczne przykłady few-shot z incydentów zweryfikowanych przez analityków |
| `AI_CLONE_SIMILARITY_THRESHOLD` | `0.85` | Próg oznaczania klonów potwierdzonych kampanii na innych domenach |
| `AI_STRICT_QUOTE_VERIFICATION` | `true` | Sygnał LLM bez cytatu obecnego w treści jest odrzucany |
| `AGGREGATOR_MULTI_MODULE_MODE` | `primary` | `primary` — jeden incydent na stronę; `all_significant` — incydent per moduł z naruszeniami |
| `CRAWLER_EXPAND_SHORT_LINKS` | `false` | Rozwijanie skracaczy / link-in-bio do domen docelowych (anty-SSRF) |
| `CRAWLER_RESPECT_ROBOTS` | `true` | Respektowanie `robots.txt` (cache per domena, `CRAWLER_ROBOTS_TTL_HOURS`) |
| `CRAWLER_PER_HOST_DELAY_SECONDS` | `2` | Minimalny odstęp między żądaniami do jednego hosta (lub `Crawl-delay`, jeśli większy) |
| `WATCHLIST_SEED_ON_START` | `true` | Startowa watchlista z `data/watchlist_seed.json` i domen podmiotów z rejestru KNF |
| `DISCOVERY_ENABLED` | `false` | Odkrywanie nowych URL-i przez SearXNG (profil `discovery`) według `data/discovery_queries.json` |
| `DISCOVERY_CRON` | `0 */6 * * *` | Harmonogram rund discovery (UTC); limity: `DISCOVERY_QUERIES_PER_RUN`, `DISCOVERY_MAX_NEW_URLS_PER_RUN` |
| `DISCOVERY_REVISIT_DAYS` | `7` | Po ilu dniach URL znaleziony wcześniej może wrócić do kolejki |
| `KNF_REFRESH_CRON` | puste | Cykliczne odświeżanie snapshotu rejestru KNF z oficjalnych list (`python -m scripts.refresh_knf_registry`) |

Zmienne frontendu (`REACT_APP_INVESTWATCH_API_URL`, `REACT_APP_ALERT_THRESHOLD`) opisuje [frontend/.env.example](frontend/.env.example). Są wklejane do bundla w czasie builda — nie umieszczaj w nich sekretów.

## Testy i audyt bezpieczeństwa (Cybersec)

```bash
cd backend
pytest -q                    # testy Playwright wymagają: pip install -r requirements-playwright.txt && playwright install chromium
pip-audit -r requirements-dev.txt -r requirements-playwright.txt
python -m scripts.evaluate_detection --mode both   # Precision/Recall/F1 na data/eval_golden_dataset.json (reguły vs Ollama)
# instalacja Ollama, wybór modelu pod sprzęt i benchmark krok po kroku: docs/ollama-llm-setup.md

cd ../frontend
yarn audit
```

Wyniki audytów i analiza wpływu: [docs/security-licenses.md](docs/security-licenses.md).

## Tryb demo i znane ograniczenia

- **Fallback bez Ollama:** jeżeli Ollama na hoście jest niedostępna, system automatycznie działa w trybie `demo_fallback` (silnik deterministyczny 18 reguł UKNF + analiza DOM/CSS + etykietowane dane startowe w SQLite).
- **Chodzenie po linkach:** zadanie `public_url` i cel watchlisty przyjmują `follow_depth` (0–2, domyślnie 0) i `follow_max_pages` (≤30); odwiedzane są tylko podstrony tej samej domeny, najpierw regulaminy, ostrzeżenia o ryzyku i oferta.
- **Lokalny snapshot KNF:** `data/knf_registry_snapshot.json` zawiera udokumentowany lokalny snapshot rejestrów KNF (data w polu `snapshot_date`) wraz z fikcyjnymi podmiotami `[DEMO]` dla lokalnych mock-stron — nie zastępuje bieżącej weryfikacji statusu prawnego w KNF.
- **Wskaźnik `risk_score` (0.00–1.00):** służy analitykowi do priorytetyzacji i kalibracji progu FP/FN; nie stanowi wiążącego rozstrzygnięcia prawnego.
- **Tryb DEMO panelu:** gdy backend jest nieosiągalny, panel działa w jawnie oznaczonym trybie DEMO (heurystyka regułowa w przeglądarce, nie AI, dane w `localStorage`). Panel nie wysyła obrazów do analizy; backend opcjonalnie analizuje zrzuty ekranu stron modelem VLM (`OLLAMA_VISION_ENABLED=true`, wymaga Playwrighta i modelu z obsługą obrazów).
- **Kontrakt API:** pełna specyfikacja endpointów i zdarzeń WebSocket w [CONTRACT.md](CONTRACT.md).

## Konwencje repozytorium

- **Końcówki linii:** [`.gitattributes`](.gitattributes) wymusza `LF` w repozytorium i w kopii roboczej (także na Windowsie, niezależnie od `core.autocrlf`) — istotne dla `Dockerfile`, `nginx.conf` i skryptów. Pliki binarne (`.docx`, `.pdf`, obrazy, SQLite) nie są konwertowane.
- **Sekrety:** tylko szablony `.env.example` (root i `frontend/`); właściwe pliki `.env` są ignorowane przez Git.
- **Kontrakt:** zmiany API wyłącznie addytywne, uzgadniane w [CONTRACT.md](CONTRACT.md) (aktualnie `1.2.0`).
