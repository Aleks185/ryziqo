# Bezpieczeństwo i Licencje Open Source (`Ryziqo`)

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
| `playwright` (opcjonalnie, `INSTALL_PLAYWRIGHT=true`) + Chromium | Render stron JS, computed styles, zrzuty ekranu dla VLM | Apache-2.0 (Chromium: BSD-3-Clause i licencje komponentów) |
| `sqlite3` (stdlib) | Relacyjna baza metadanych | PSF |
| `pytest` | Testy jednostkowe i integracyjne | MIT |
| `pip-audit` | Audyt podatności łańcucha dostaw (PyPA) | Apache-2.0 |
| SearXNG (opcjonalnie, profil `discovery`, osobny kontener) | Lokalna metawyszukiwarka do odkrywania nowych treści | AGPL-3.0 (używana bez modyfikacji, jako niezależna usługa przez HTTP) |
| `openpyxl` (opcjonalnie, nie instalowany domyślnie) | Odczyt list KNF w XLSX przy odświeżaniu rejestru | MIT |

### Wykaz głównych bibliotek Frontend (bezpłatne wykorzystanie komercyjne)

| Pakiet | Rola | Licencja |
|---|---|---|
| `react` / `react-dom` | Biblioteka UI | MIT |
| `react-router-dom` | Routing SPA | MIT |
| `react-scripts` (CRA) + `@craco/craco` | Build i dev server | MIT / Apache-2.0 |
| `tailwindcss`, `tailwind-merge`, `class-variance-authority` | Stylowanie | MIT |
| `@radix-ui/*` (shadcn/ui) | Dostępne komponenty UI | MIT |
| `recharts` | Wykresy trendów | MIT |
| `sonner` | Powiadomienia (toast) | MIT |
| `lucide-react` | Ikony | ISC |
| `date-fns` | Formatowanie dat | MIT |
| `nginx` (`nginx:1.27-alpine`) | Serwer statyki + reverse proxy | BSD-2-Clause |
| IBM Plex Sans / Mono / Serif | Fonty | SIL OFL 1.1 |

### Rekomendowane modele Open Source (Ollama on-premise)
- `gemma3:4b` / `gemma4` — otwarte wagi Gemma (do lokalnej inferencji)
- `nomic-embed-text` — Apache-2.0 (opcjonalne embeddingi lokalne)

## 2. Zabezpieczenia wdrożone w kodzie

- **Ochrona anty-SSRF (`backend/app/scraper/ssrf.py`):** dopuszcza wyłącznie `http`/`https`, rozwiązuje DNS przed połączeniem i na każdym przekierowaniu, blokuje `localhost`, adresy prywatne (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`), link-local/metadata (`169.254.0.0/16`, `fe80::/10`) oraz uwierzytelnianie w URL.
- **Izolacja sekretów:** brak twardo zakodowanych kluczy; `.env` w `.gitignore`, szablon w `.env.example`.
- **Kontener non-root:** `backend/Dockerfile` uruchamia aplikację jako `appuser`.
- **Single origin przez Nginx:** w Dockerze przeglądarka łączy się tylko z `frontend` (Nginx), który przekazuje `/api/` i `/ws/` do backendu — brak potrzeby szerokiego CORS i brak *mixed content*.
- **Nagłówki bezpieczeństwa (Nginx):** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `server_tokens off`.
- **Brak telemetrii w panelu:** usunięto odziedziczony z prototypu Emergent tracker PostHog z nagrywaniem sesji (`ap.emergent.sh`), skrypt `assets.emergent.sh` oraz pakiety `@emergentbase/*`. Bundel produkcyjny nie zawiera odwołań do tych usług. Jedynym pozostałym zasobem zewnętrznym są fonty z Google Fonts (do zastąpienia lokalnym hostingiem przy wdrożeniu offline).
- **Obraz frontendu bez kodu źródłowego i sekretów:** build bez source map (`GENERATE_SOURCEMAP=false`), `.env` wykluczony przez `.dockerignore`, w obrazie końcowym tylko statyczne pliki i Nginx.
- **Analiza na żądanie (`/api/v1/analyze/*`):** wklejona treść jest walidowana (20–20 000 znaków) i escapowana przed przetworzeniem (znaczniki HTML traktowane jako tekst); `analyze/url` przechodzi tę samą walidację anty-SSRF i limity co kolejka crawlera; Nginx ogranicza rozmiar żądania do `1 MB`.
- **Odporność silnika AI na manipulacje:** treść strony w piaskownicy `<untrusted_content>`, wykrywanie prompt injection w ukrytym tekście (`AI_PROMPT_INJECTION`, blokuje weto FP), weryfikacja cytatów LLM w tekście źródłowym oraz normalizacja homoglifów i znaków zero-width (`backend/app/ai/`).
- **Anty-SSRF dla rozwijania linków:** opcjonalne rozwijanie skracaczy (`CRAWLER_EXPAND_SHORT_LINKS`) waliduje każdy krok przekierowania tą samą funkcją `validate_public_url`.
- **Limity scrapera:** limit rozmiaru odpowiedzi (`2 MB`), timeouty, limit przekierowań (`5`), łagodne tempo żądań.
- **Etyka crawlera:** respektowanie `robots.txt` (cache per domena, `CRAWLER_RESPECT_ROBOTS`) i `Crawl-delay`, odstęp między żądaniami do jednego hosta (`CRAWLER_PER_HOST_DELAY_SECONDS`), jawny User-Agent bez podszywania się pod przeglądarki.
- **Discovery i chodzenie po linkach:** każdy URL z SearXNG i każda podstrona przechodzi kanonikalizację, listę wykluczeń domen i `validate_public_url`; liczba nowych URL-i na rundę i podstron na zadanie jest ograniczona. SearXNG nie ma portu na hoście (dostępny tylko w sieci Dockera).
- **Odświeżanie rejestru KNF:** pobieranie z tymi samymi limitami i anty-SSRF; zapis atomowy obok bazy, a kategoria, która zwróci mniej niż połowę poprzednich wpisów, zostaje bez zmian (ochrona przed zmianą struktury strony).

## 3. Wynik audytu `pip-audit`

- **Data audytu:** `2026-11-21`
- **Komenda:** `backend\.venv\Scripts\pip-audit.exe -r requirements-dev.txt -r requirements-playwright.txt` (pip-audit `2.10.1`, Python `3.15.2`) — ponowione po wdrożeniu detekcji v2 (commit `a891f9e`, bez nowych zależności Pythona)
- **Wynik:** `No known vulnerabilities found` (kod wyjścia `0`, **0 znanych podatności** we wszystkich zainstalowanych pakietach).

## 4. Wynik audytu `yarn audit` (frontend)

- **Data audytu:** `2026-11-21`
- **Komenda:** `yarn audit` (Yarn `1.22.22`, `node:20-alpine`), 1560 pakietów
- **Wynik:** **35 zgłoszeń** — 8 low, 16 moderate, 11 high.
- **Analiza wpływu:**
  - Niemal wszystkie zgłoszenia pochodzą z narzędzi builda/dev servera `react-scripts` 5 (`svgo`, `body-parser`, `launch-editor`, `fast-uri`, `qs`, `serialize-javascript`, `postcss-selector-parser`). Działają one wyłącznie w czasie `yarn build` / `yarn start` i **nie trafiają do obrazu produkcyjnego** (Nginx serwuje tylko statyczny build).
  - `zod` (high) i `axios` → `follow-redirects` (high) są zadeklarowane w `package.json` (pozostałość szablonu), ale **nie są importowane przez kod aplikacji**, więc nie występują w bundlu.
- **Rekomendacja:** usunąć nieużywane zależności (`axios`, `zod`, `@hookform/resolvers` i inne niewykorzystywane pakiety szablonu) oraz rozważyć migrację z niewspieranego CRA na Vite, co usunie większość zgłoszeń łańcucha narzędzi.
