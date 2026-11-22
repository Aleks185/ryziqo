# Ryziqo — monitoring treści inwestycyjnych dla UKNF

Prototyp przygotowany na HackNation 2026. System pobiera i analizuje materiały promocyjne oraz oferty finansowe, a wyniki trafiają do panelu analityka UKNF. Działa w całości lokalnie: model językowy uruchamia Ollama, bez płatnych zewnętrznych API.

Moduły analizy:

1. **Finfluencerzy i podmioty trzecie** — reklamy polskich i zagranicznych firm inwestycyjnych.
2. **Informacja o ryzyku** — 18 kryteriów MiFID II / rozp. del. 2017/565 oraz analiza układu strony (DOM/CSS).
3. **Shadow advisory** — nieautoryzowane doradztwo inwestycyjne (art. 76, 2 i 3 u.o.i.f.).

Oprócz panelu analityka jest publiczny formularz, w którym obywatel może sprawdzić tekst, adres URL lub zrzut ekranu.

## Dokumentacja

| Dokument | Zawartość |
|---|---|
| [CONTRACT.md](CONTRACT.md) | Kontrakt REST i WebSocket między backendem a frontendem (`1.4.0`) |
| [docs/backend-architecture.md](docs/backend-architecture.md) | Backend: przepływ danych, scraper, moduły AI, baza danych |
| [docs/frontend-architecture.md](docs/frontend-architecture.md) | Frontend: widoki, stan aplikacji, tryb DEMO, Nginx, konwencje |
| [frontend/README.md](frontend/README.md) | Uruchomienie i skrypty frontendu |
| [docs/ollama-llm-setup.md](docs/ollama-llm-setup.md) | Instalacja Ollama, dobór modelu do sprzętu, benchmark (EN) |
| [docs/ai-detection-improvement-plan.md](docs/ai-detection-improvement-plan.md) | Plan usprawnień silnika detekcji |
| [docs/ai-workflow.md](docs/ai-workflow.md) | Proces pracy zespołu z asystentami AI |
| [docs/security-licenses.md](docs/security-licenses.md) | Bezpieczeństwo, licencje, wyniki audytów zależności |
| [docs/spec-checklist.md](docs/spec-checklist.md) | Zgodność ze specyfikacją wyzwania: zrobione i do zrobienia |
| [docs/backend-audit-checklist.md](docs/backend-audit-checklist.md) | Checklista niezależnego przeglądu backendu |
| [docs/raport-wdrozenia-analizy.md](docs/raport-wdrozenia-analizy.md) | Raport wdrożenia: środowisko, model, wyniki testów |
| [docs/raport-etap-2.md](docs/raport-etap-2.md) | Odbiór etapu 2: baza zgłoszeń, kampanie, diagnostyka |
| [docs/frontend/](docs/frontend/) | Dokumenty historyczne z prototypowania frontendu (PRD, plan, wytyczne graficzne) |

## Struktura repozytorium

```text
backend/     FastAPI, scraper z ochroną anty-SSRF, moduły AI 1–3, SQLite
frontend/    React 19 + Tailwind; w Dockerze serwowany przez Nginx
data/        reguły UKNF, snapshot rejestrów KNF, mock-strony demo, dane startowe, zbiór ewaluacyjny
docs/        dokumentacja
deploy/      konfiguracja SearXNG (profil discovery)
```

## Wymagania

- Docker i Docker Compose — zalecany sposób uruchomienia.
- RAM: 4 GB bez modelu językowego (tylko reguły), 8–16 GB z lokalnym modelem w Ollama.
- Opcjonalnie [Ollama](https://ollama.com/) na hoście (`ollama pull gemma3:4b`) albo w kontenerze (profil `ai`).
- **GPU (zalecane dla lokalnego LLM):** karta NVIDIA z min. 6–8 GB VRAM (np. RTX 4060 8 GB mieści cały `gemma3:4b`, ~50–60 tokenów/s; na CPU kilka–kilkanaście). Dla Ollamy w kontenerze wymagany jest dostęp Dockera do GPU: Docker Desktop z backendem WSL2 (Windows) lub [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) (Linux). Test: `docker run --rm --gpus all ubuntu nvidia-smi -L` powinien wypisać kartę.
  - Serwis `ollama` w `docker-compose.yml` rezerwuje GPU (`deploy.resources.reservations.devices`). **Na maszynie bez karty NVIDIA usuń ten blok**, inaczej kontener nie wystartuje (model będzie wtedy działał na CPU).
  - Weryfikacja, że model działa na GPU:
    ```powershell
    docker logs investwatch-ollama 2>&1 | Select-String "inference compute|offloaded"
    # oczekiwane: library=CUDA ... oraz "offloaded 35/35 layers to GPU"
    docker exec investwatch-ollama ollama run gemma3:4b "test" --keepalive 2m --verbose   # "eval rate" ~50+ tokens/s
    docker exec investwatch-ollama ollama ps   # kolumna PROCESSOR: 100% GPU
    ```
    Backend wyładowuje model po zapytaniu (`keep_alive`), więc puste `ollama ps` jest normalne — miarodajne są logi z ładowania.
- Bez Dockera: Python 3.11+ (backend), Node.js 20+ i Yarn 1.22 (frontend).

## Uruchomienie (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

Warianty:

- **Ollama w kontenerze:** w `.env` ustaw `OLLAMA_BASE_URL=http://ollama:11434`, potem `docker compose --profile ai up --build`. Modele pobierają się przy pierwszym starcie.
- **Odkrywanie nowych treści (SearXNG):** w `.env` ustaw `DISCOVERY_ENABLED=true`, potem `docker compose --profile discovery up --build`.
- **Strony renderowane JavaScriptem:** w `.env` ustaw `INSTALL_PLAYWRIGHT=true` i `CRAWLER_USE_PLAYWRIGHT_FALLBACK=true`, potem `docker compose build`.

Adresy po uruchomieniu:

| Co | Adres |
|---|---|
| Panel analityka | `http://localhost:3000` |
| Formularz obywatela | `http://localhost:3000/public` |
| API (health) | `http://localhost:8000/api/v1/health` |
| Swagger / OpenAPI | `http://localhost:8000/docs` |
| WebSocket alertów | `ws://localhost:8000/ws/alerts` |
| Przykładowa mock-strona | `http://localhost:8000/mock-sites/broker_promo_hidden_risk.html` |

W Dockerze Nginx przekazuje `/api/` i `/ws/` do backendu, więc przeglądarka łączy się tylko z portem `3000`. Pełna lista endpointów (analiza, watchlista, discovery, rejestr KNF, raporty modułów) jest w [CONTRACT.md](CONTRACT.md).

## Uruchomienie bez Dockera

Backend (port `8000`):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (port `3000`, łączy się z `http://localhost:8000/api/v1`):

```bash
cd frontend
cp .env.example .env
yarn install
yarn start
```

## Konfiguracja

Wszystkie parametry są opisane w [.env.example](.env.example). Właściwy plik `.env` jest ignorowany przez Git. Najważniejsze zmienne:

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` (Docker: `http://host.docker.internal:11434`) | Adres Ollama |
| `OLLAMA_MODEL` | `gemma3:4b` | Model do analizy semantycznej |
| `OLLAMA_NUM_PREDICT` / `OLLAMA_NUM_CTX` | `1024` / `4096` | Limit tokenów odpowiedzi i okno kontekstu |
| `OLLAMA_VISION_ENABLED` | `false` | Analiza zrzutów ekranu modelem wizyjnym (wymaga Playwrighta i modelu z obsługą obrazów) |
| `INSTALL_OCR` | `true` | Build-arg Dockera: lokalny OCR (RapidOCR), gdy model wizyjny jest niedostępny |
| `INSTALL_PLAYWRIGHT` | `false` | Build-arg Dockera: Chromium dla stron renderowanych JavaScriptem |
| `DATABASE_PATH` | `../data/investwatch.db` (Docker: `/data/investwatch.db`) | Baza SQLite |
| `OBJECT_STORE_DIR` | `../data/object_store` (Docker: `/data/object_store`) | Surowe HTML i JSON pobranych stron |
| `HIGH_RISK_ALERT_THRESHOLD` | `0.65` | Próg alertów `high_risk_alert`; w Dockerze także próg alertów w panelu |
| `FRONTEND_PORT` | `3000` | Port panelu na hoście |

Crawler:

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `CRAWLER_SCHEDULE_MINUTES` / `CRAWLER_CRON` | `15` / puste | Interwał skanowania albo wyrażenie crontab (UTC), które go zastępuje |
| `CRAWLER_USE_PLAYWRIGHT_FALLBACK` | `false` | Renderowanie w Chromium stron z małą ilością tekstu |
| `CRAWLER_PLAYWRIGHT_MIN_TEXT_CHARS` | `400` | Próg widocznego tekstu, poniżej którego strona jest renderowana |
| `CRAWLER_RESPECT_ROBOTS` | `true` | Respektowanie `robots.txt` (cache per domena, `CRAWLER_ROBOTS_TTL_HOURS`) |
| `CRAWLER_PER_HOST_DELAY_SECONDS` | `2` | Minimalny odstęp między żądaniami do jednego hosta (lub `Crawl-delay`, jeśli większy) |
| `CRAWLER_EXPAND_SHORT_LINKS` | `false` | Rozwijanie skracaczy i stron link-in-bio (z kontrolą anty-SSRF) |
| `CRAWLER_PROXIES` | puste | Proxy rotowane per żądanie (`http://...`, `socks5://...`) |
| `DEDUP_SIMILARITY_THRESHOLD` | `0.92` | Podobieństwo, powyżej którego ponowny skan aktualizuje istniejący incydent |
| `WATCHLIST_SEED_ON_START` | `true` | Startowa watchlista z `data/watchlist_seed.json` i domen podmiotów z rejestru KNF |

Silnik AI:

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `AI_PROMPT_CONTENT_CHARS` | `9000` | Budżet znaków treści w prompcie |
| `AI_RAG_FEW_SHOT_ENABLED` | `true` | Przykłady few-shot z incydentów zweryfikowanych przez analityków |
| `AI_CLONE_SIMILARITY_THRESHOLD` | `0.85` | Próg oznaczania klonów potwierdzonych kampanii na innych domenach |
| `AI_STRICT_QUOTE_VERIFICATION` | `true` | Sygnał modelu bez cytatu obecnego w treści jest odrzucany |
| `AGGREGATOR_MULTI_MODULE_MODE` | `primary` | `primary`: jeden incydent na stronę; `all_significant`: incydent na każdy moduł z naruszeniami |

Discovery, rejestr KNF, dowody:

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `DISCOVERY_ENABLED` | `false` | Wyszukiwanie nowych adresów przez SearXNG według `data/discovery_queries.json` |
| `DISCOVERY_CRON` | `0 */6 * * *` | Harmonogram rund discovery (UTC); limity: `DISCOVERY_QUERIES_PER_RUN`, `DISCOVERY_MAX_NEW_URLS_PER_RUN` |
| `DISCOVERY_REVISIT_DAYS` | `7` | Po ilu dniach znany adres może wrócić do kolejki |
| `KNF_REFRESH_CRON` | puste | Cykliczne odświeżanie snapshotu rejestru KNF (`python -m scripts.refresh_knf_registry`) |
| `KNF_SYNC_USER_AGENT` | nagłówek Chrome | User-Agent synchronizacji rejestru (knf.gov.pl odrzuca nagłówki botów); crawler treści nadal przedstawia się jako bot |
| `EVIDENCE_TSA_URL` | puste | Serwer znaczników czasu RFC 3161 dla paczek dowodowych ZIP (np. `https://freetsa.org/tsr`) |

Zmienne frontendu (`REACT_APP_INVESTWATCH_API_URL`, `REACT_APP_ALERT_THRESHOLD`) opisuje [frontend/README.md](frontend/README.md). Trafiają do kodu przeglądarki w czasie builda, więc nie mogą zawierać sekretów.

## Testy i audyt

```bash
cd backend
pytest -q
pip-audit -r requirements-dev.txt -r requirements-playwright.txt
python -m scripts.evaluate_detection --mode both   # precision / recall / F1: reguły vs Ollama

cd ../frontend
yarn audit
```

Testy Playwright wymagają `pip install -r requirements-playwright.txt` i `playwright install chromium`. Wyniki audytów: [docs/security-licenses.md](docs/security-licenses.md). Frontend nie ma testów automatycznych.

## Ograniczenia

- Bez Ollama backend działa w trybie `demo_fallback`: deterministyczne reguły UKNF, analiza DOM/CSS i dane startowe w SQLite.
- Bez backendu panel przechodzi w oznaczony tryb DEMO: prosta heurystyka w przeglądarce (to nie AI), dane w `localStorage`. Analiza URL i zrzutów ekranu wymaga backendu.
- Chodzenie po linkach (`follow_depth` 0–2, `follow_max_pages` ≤ 30) obejmuje tylko podstrony tej samej domeny; najpierw regulaminy, ostrzeżenia o ryzyku i ofertę.
- `data/knf_registry_snapshot.json` to lokalny snapshot rejestrów KNF (data w `snapshot_date`) z fikcyjnymi podmiotami `[DEMO]` dla mock-stron. Nie zastępuje bieżącej weryfikacji w KNF.
- `risk_score` (0–1) służy do priorytetyzacji i kalibracji progu. Nie jest rozstrzygnięciem prawnym.
- API nie ma uwierzytelniania.

## Konwencje

- [`.gitattributes`](.gitattributes) wymusza końcówki linii `LF` (ważne dla `Dockerfile`, `nginx.conf` i skryptów). Pliki binarne nie są konwertowane.
- W repozytorium są tylko szablony `.env.example` (główny i `frontend/`).
- Zmiany API są wyłącznie addytywne i trafiają do [CONTRACT.md](CONTRACT.md).
