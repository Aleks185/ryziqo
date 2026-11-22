# Ryziqo (#InvestWatch) — monitoring treści inwestycyjnych dla UKNF

Prototyp na HackNation 2026. Crawler pobiera materiały promocyjne i oferty finansowe, trzy moduły analityczne oceniają ryzyko, wyniki trafiają do panelu analityka. Całość działa lokalnie, model językowy uruchamia Ollama, bez płatnych API.

1. **Finfluencerzy i podmioty trzecie** — reklamy firm inwestycyjnych publikowane przez osoby trzecie.
2. **Informacja o ryzyku** — 18 kryteriów MiFID II / rozp. del. 2017/565 oraz analiza układu strony (DOM/CSS).
3. **Shadow advisory** — nieautoryzowane doradztwo inwestycyjne (art. 76, 2 i 3 u.o.i.f.).

```text
backend/     FastAPI, crawler z ochroną anty-SSRF, moduły AI 1–3, SQLite + object store
frontend/    React 19 + Tailwind, w Dockerze serwowany przez Nginx
data/        reguły UKNF, snapshot rejestru KNF, mock-strony, zbiór ewaluacyjny
deploy/      konfiguracja SearXNG (profil discovery)
docs/        dokumentacja szczegółowa
```

## Quick Start

```bash
cp .env.example .env   # opcjonalnie — każda zmienna ma wartość domyślną
docker compose up --build
```

Pierwszy build trwa kilka–kilkanaście minut (obraz backendu ~2 GB z Chromium i OCR; mniejszy: `INSTALL_PLAYWRIGHT=false`, `INSTALL_OCR=false` w `.env`).

| Co | Adres |
|---|---|
| Panel analityka | http://localhost:3000 |
| Formularz obywatela | http://localhost:3000/public |
| API / Swagger | http://localhost:8000/docs |
| WebSocket alertów | ws://localhost:8000/ws/alerts |

Bez Ollamy backend działa na regułach UKNF (`demo_fallback`). Modele AI:

- **Ollama na hoście:** `ollama pull gemma3:4b` i `ollama pull nomic-embed-text`; backend łączy się z `http://host.docker.internal:11434` (domyślnie). Na Linuksie Ollama musi słuchać na wszystkich interfejsach: `sudo systemctl edit ollama` → `[Service]` `Environment="OLLAMA_HOST=0.0.0.0"`, potem `sudo systemctl restart ollama`.
- **Ollama w kontenerze:** `OLLAMA_BASE_URL=http://ollama:11434` w `.env`, potem `docker compose --profile ai up --build` (modele pobierają się automatycznie). Z GPU NVIDIA: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ai up --build`.
- **Sprawdzenie:** `curl http://localhost:8000/api/v1/health` — `"mode": "live"` oznacza aktywne AI, `"demo_fallback"` — tryb reguł; log backendu „aktywny tryb fallback” oznacza brak połączenia.
- **Discovery (SearXNG):** `DISCOVERY_ENABLED=true` w `.env`, potem `docker compose --profile discovery up --build`.

## Wymagania sprzętowe

- Docker i Docker Compose.
- RAM: 4 GB bez modelu językowego, 8–16 GB z lokalnym modelem.
- Dla Ollamy zalecana karta NVIDIA z min. 6–8 GB VRAM (`gemma3:4b` ~50 tokenów/s; na CPU kilka–kilkanaście). Serwis `ollama` (profil `ai`) domyślnie działa na CPU; GPU włącza `docker-compose.gpu.yml` (wymaga NVIDIA Container Toolkit lub Docker Desktop z WSL2).
- Bez Dockera: Python 3.11+, Node.js 20+, Yarn 1.22 (`uvicorn app.main:app` w `backend/`, `yarn start` w `frontend/`).

## Konfiguracja

Wszystkie parametry opisuje [.env.example](.env.example); `.env` jest ignorowany przez Git, sekrety wyłącznie tam.

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Adres Ollamy |
| `OLLAMA_MODEL` | `gemma3:4b` | Model analizy semantycznej |
| `OLLAMA_VISION_ENABLED` | `false` | Analiza zrzutów ekranu modelem wizyjnym |
| `HIGH_RISK_ALERT_THRESHOLD` | `0.65` | Próg alertów `high_risk_alert` (także w panelu) |
| `DATABASE_PATH` / `OBJECT_STORE_DIR` | `/data/...` | SQLite i surowe HTML/JSON pobranych stron |
| `CRAWLER_SCHEDULE_MINUTES` / `CRAWLER_CRON` | `15` / puste | Interwał skanowania albo crontab (UTC) |
| `CRAWLER_PROXIES` | puste | Proxy rotowane per żądanie |
| `CRAWLER_RESPECT_ROBOTS` | `true` | Respektowanie `robots.txt` i `Crawl-delay` |
| `INSTALL_PLAYWRIGHT` | `true` | Build-arg: Chromium dla stron renderowanych JS (~400 MB) |
| `CRAWLER_USE_PLAYWRIGHT_FALLBACK` | `false` | Renderowanie w Chromium stron z małą ilością tekstu |
| `DISCOVERY_ENABLED` | `false` | Wyszukiwanie nowych adresów przez SearXNG |
| `FRONTEND_PORT` / `APP_PORT` | `3000` / `8000` | Porty na hoście |

## Testy i audyt zależności

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q                          # bez Ollamy; testy Playwrighta pomijane, gdy nie jest zainstalowany
pip-audit -r requirements-dev.txt
python -m scripts.evaluate_detection --mode both   # precision / recall / F1
cd ../frontend && yarn install --frozen-lockfile && yarn audit
```

Wyniki audytów: [docs/security-licenses.md](docs/security-licenses.md).

## Dokumentacja

[CONTRACT.md](CONTRACT.md) (REST i WebSocket) · [docs/](docs/): architektura backendu i frontendu, konfiguracja Ollamy, proces pracy z asystentami AI, zgodność ze specyfikacją.

## Ograniczenia

- API nie ma uwierzytelniania.
- `risk_score` (w raporcie analizy i bazie zgłoszeń: 0–100 %; w incydentach API nadal 0–1, UI pokazuje jako %) służy do priorytetyzacji i kalibracji progu, nie jest rozstrzygnięciem prawnym.
- etoro.com i trading212.com odpowiadają `403` (Cloudflare) na User-Agent crawlera; crawler nie obchodzi zabezpieczeń antybotowych, więc domeny są poza startową watchlistą.
