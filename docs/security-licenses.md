# Bezpieczeństwo i Licencje Open Source (`#InvestWatch`)

## 1. Zgodność z wymogiem 100% Open Source & On-Premise

System nie korzysta z żadnych płatnych zewnętrznych API. Inferencja LLM oraz embeddingi działają wyłącznie lokalnie poprzez Ollama na hoście (lub deterministyczny fallback w trybie offline).

### Wykaz głównych bibliotek Backend (bezpłatne wykorzystanie komercyjne)

| Pakiet | Rola | Licencja |
|---|---|---|
| `fastapi` | Framework REST & WebSocket | MIT |
| `uvicorn` | Serwer ASGI | BSD-3-Clause |
| `pydantic` / `pydantic-settings` | Walidacja kontraktów i konfiguracji `.env` | MIT |
| `httpx` | Asynchroniczny klient HTTP (scraper + Ollama) | BSD-3-Clause |
| `beautifulsoup4` | Parser HTML i ekstrakcja metryk DOM/CSS | MIT |
| `apscheduler` | Harmonogram cyklicznych zadań (Cron/Interval) | MIT |
| `sqlite3` (stdlib) | Relacyjna baza metadanych | PSF |
| `pytest` | Testy jednostkowe i integracyjne | MIT |
| `pip-audit` | Audyt podatności łańcucha dostaw (PyPA) | Apache-2.0 |

### Rekomendowane modele Open Source (Ollama on-premise)
- `gemma3:4b` / `gemma4` — otwarte wagi Gemma (do lokalnej inferencji)
- `nomic-embed-text` — Apache-2.0 (opcjonalne embeddingi lokalne)

## 2. Zabezpieczenia wdrożone w kodzie

- **Ochrona anty-SSRF (`backend/app/scraper/ssrf.py`):** dopuszcza wyłącznie `http`/`https`, rozwiązuje DNS przed połączeniem i na każdym przekierowaniu, blokuje `localhost`, adresy prywatne (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`), link-local/metadata (`169.254.0.0/16`, `fe80::/10`) oraz uwierzytelnianie w URL.
- **Izolacja sekretów:** brak twardo zakodowanych kluczy; `.env` w `.gitignore`, szablon w `.env.example`.
- **Kontener non-root:** `backend/Dockerfile` uruchamia aplikację jako `appuser`.
- **Limity scrapera:** limit rozmiaru odpowiedzi (`2 MB`), timeouty, limit przekierowań (`5`), łagodne tempo żądań.

## 3. Wynik audytu `pip-audit`

- **Data audytu:** `2026-11-21`
- **Komenda:** `backend\.venv\Scripts\pip-audit.exe` (pip-audit `2.10.1`, Python `3.15.2`)
- **Wynik:** `No known vulnerabilities found` (kod wyjścia `0`, **0 znanych podatności** we wszystkich zainstalowanych pakietach).
