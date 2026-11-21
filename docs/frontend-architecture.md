# Architektura i Implementacja Frontendu `#InvestWatch`

Opis techniczny panelu analitycznego `#InvestWatch` (HackNation UKNF 2026) — aplikacji **React 19** dla analityków nadzoru UKNF, serwowanej w produkcji przez **Nginx**, który pełni też rolę reverse proxy do backendu. Kontrakt danych: [CONTRACT.md](../CONTRACT.md).

> Prototyp frontendu został wygenerowany w środowisku Emergent, a następnie oczyszczony z jego integracji (telemetria, skrypty zewnętrzne, pakiety `@emergentbase/*`) — patrz [§7](#7-bezpieczeństwo-i-prywatność). Notatki projektowe z tego etapu: [frontend/PRD.md](./frontend/PRD.md), [frontend/plan.md](./frontend/plan.md), [frontend/design_guidelines.json](./frontend/design_guidelines.json).

---

## 1. Topologia uruchomieniowa (Docker Compose)

```mermaid
flowchart LR
    B["Przeglądarka analityka"] -->|"http://localhost:3000"| N["Nginx (investwatch-frontend)"]
    N -->|"/ , /static/* — statyczny build React"| S["/usr/share/nginx/html"]
    N -->|"/api/* (REST)"| API["FastAPI backend:8000"]
    N -->|"/ws/* (WebSocket Upgrade)"| API
```

- Przeglądarka komunikuje się **wyłącznie z jednym originem** (`localhost:3000`). Frontend jest budowany z `REACT_APP_INVESTWATCH_API_URL=/api/v1`, więc REST i WebSocket idą przez Nginx — bez CORS i bez problemu *mixed content*.
- Serwis `frontend` startuje dopiero, gdy `backend` przejdzie `HEALTHCHECK` (`depends_on: condition: service_healthy`).
- W developmencie lokalnym (`yarn start`, port `3000`) frontend łączy się bezpośrednio z `http://localhost:8000/api/v1` — backend musi wtedy dopuszczać ten origin w `CORS_ORIGINS` (domyślnie dopuszcza).

---

## 2. Struktura katalogu `frontend/`

```text
frontend/
├── Dockerfile                    # multi-stage: node:20-alpine (yarn build) -> nginx:1.27-alpine
├── nginx.conf                    # proxy /api/ i /ws/ -> backend:8000, SPA fallback, cache, gzip
├── nginx-security-headers.conf   # wspólne nagłówki bezpieczeństwa (include w każdej location)
├── .dockerignore                 # node_modules, build, .env (sekrety nie trafiają do obrazu)
├── .env.example                  # szablon zmiennych REACT_APP_* (właściwy .env ignorowany przez Git)
├── package.json / yarn.lock      # Yarn 1.22, CRA 5 (react-scripts) + craco
├── craco.config.js               # alias "@" -> src, ESLint react-hooks, kompatybilność z webpack-dev-server 5
├── tailwind.config.js, postcss.config.js, components.json (shadcn/ui)
├── plugins/health-check/         # opcjonalne endpointy zdrowia dev servera (ENABLE_HEALTH_CHECK=true)
├── public/index.html
└── src/
    ├── App.js                    # routing (react-router 7) + AppProvider + Toaster
    ├── pages/
    │   ├── Dashboard.jsx         # "/"               — KPI, trend, tabela incydentów, live log
    │   ├── Analyze.jsx           # "/analyze"        — analiza tekstu / URL, przykłady demo
    │   ├── IncidentDetail.jsx    # "/incidents/:id"  — uzasadnienie, cytaty dowodowe, status, druk A4
    │   ├── Calibration.jsx       # "/calibration"    — etykiety referencyjne, macierz TP/FP/TN/FN, próg
    │   └── LogPage.jsx           # "/log"            — pełny dziennik zdarzeń (REST/WS/demo)
    ├── components/               # Header, DemoBanner, IncidentTable, TrendChart, LiveLog, Badges, Logo
    │   └── ui/                   # komponenty shadcn/ui (Radix UI + Tailwind)
    ├── lib/
    │   ├── config.js             # API_URL, WS_URL, próg alertu, słowniki modułów i statusów
    │   ├── api.js                # klient REST (fetch + timeout/AbortController)
    │   ├── store.js              # AppProvider: tryb online/demo, incydenty, WebSocket, zdarzenia, i18n
    │   ├── demoEngine.js         # jawny analizator regułowy trybu DEMO (bez AI)
    │   ├── samples.js            # przykładowe treści do demonstracji Modułów 1–3
    │   ├── i18n.js               # słowniki PL / EN
    │   └── utils.js
    ├── hooks/use-toast.js
    └── constants/testIds/        # stałe data-testid (kebab-case)
```

---

## 3. Konfiguracja (`REACT_APP_*`)

CRA wkleja zmienne do bundla **w czasie builda** — zmiana wymaga przebudowania obrazu (`docker compose up --build`).

| Zmienna | Dev lokalny (`frontend/.env`) | Docker (build arg w `docker-compose.yml`) | Opis |
|---|---|---|---|
| `REACT_APP_INVESTWATCH_API_URL` | `http://localhost:8000/api/v1` | `/api/v1` | Bazowy adres REST. Może być pełnym URL albo ścieżką relatywną. |
| `REACT_APP_ALERT_THRESHOLD` | `0.7` | `${HIGH_RISK_ALERT_THRESHOLD:-0.65}` | Próg `risk_score`, od którego panel pokazuje alert (toast). W Dockerze spójny z progiem backendu. |
| `ENABLE_HEALTH_CHECK` | `false` | — | Endpointy zdrowia dev servera (tylko `yarn start`). |
| `FRONTEND_PORT` (root `.env`) | — | `3000` | Port hosta, na którym Nginx wystawia panel. |

Adres WebSocket jest wyliczany w `config.js` z `API_URL`: `http(s)://host/api/v1` → `ws(s)://host/ws/alerts`. Ścieżka relatywna jest najpierw rozwiązywana względem `window.location.origin`.

---

## 4. Warstwa stanu i tryby pracy (`lib/store.js`)

1. **Start:** `AppProvider` wywołuje `GET /health`, a następnie `GET /incidents?limit=500` (zapamiętuje też `knf_snapshot_date`).
2. **Tryb `online`:** dane z backendu, otwarty WebSocket `/ws/alerts` z ponawianiem połączenia (backoff wykładniczy `2^n s`, maks. 5 prób, potem status `offline` bez dalszego zalewania konsoli błędami). Karta incydentu dociąga pełny `IncidentDetail` (`GET /incidents/{id}` z `raw_text_preview`), bo lista go nie zawiera.
3. **Tryb `demo`:** gdy backend nie odpowiada (lub strona HTTPS wskazuje na API HTTP — *mixed content*), panel przełącza się na **jawny analizator regułowy** w przeglądarce (`demoEngine.js`: słowa-klucze dla Modułów 1–3, cytaty wycinane dosłownie z tekstu). Tworzy on rekordy **w tym samym kształcie `Incident` co backend** (`is_demo_fallback: true`, `model_used: "demo-heuristic-v1 (przeglądarka)"`), trzymane w `localStorage` (`investwatch.demo.incidents.v2`). `DemoBanner` pokazuje przyczynę i adres API. Analiza URL jest w tym trybie niedostępna.
4. **Alerty:** incydent z `risk_score ≥ ALERT_THRESHOLD` generuje jednorazowy toast (deduplikacja po `id`).
5. **i18n:** PL (domyślnie) / EN, wybór zapamiętany w `localStorage` (`investwatch.lang`).

---

## 5. Zgodność z `CONTRACT.md` (v1.1.0)

Frontend korzysta wyłącznie z modelu `Incident` i endpointów zdefiniowanych w [CONTRACT.md](../CONTRACT.md):

| Funkcja panelu | Endpoint / zdarzenie |
|---|---|
| Rejestr incydentów, pulpit, trend, filtr modułów (`module_id`) | `GET /api/v1/incidents` |
| Karta incydentu (naruszone reguły, cytaty dowodowe, metryki DOM/CSS, status w rejestrze KNF) | `GET /api/v1/incidents/{id}` |
| Analiza wklejonego tekstu / przykładów | `POST /api/v1/analyze/text` |
| Analiza adresu URL (anty-SSRF po stronie backendu) | `POST /api/v1/analyze/url` |
| Zmiana statusu sprawy | `PATCH /api/v1/incidents/{id}/status` |
| Etykieta referencyjna do kalibracji | `PATCH /api/v1/incidents/{id}/label` |
| Live Crawler Log i alerty | WebSocket `/ws/alerts`: `crawler_status`, `high_risk_alert` (→ pobranie incydentu i toast), `status_updated` (→ odświeżenie incydentu), `analysis_complete` (→ odświeżenie listy), `error` |

- **Przykłady demonstracyjne** (`lib/samples.js`) wysyłane są z `source_url: "manual://sample/S1…S6"` i `ground_truth_label` — dzięki temu backend deduplikuje je po `content_hash`, a panel oznacza je etykietą „PRZYKŁAD”.
- **Kalibracja** (macierz TP/FP/TN/FN i krzywa FP/FN) liczona jest w przeglądarce z `risk_score` i `ground_truth_label`, więc działa identycznie w obu trybach. `GET /api/v1/stats` nie jest obecnie używany.
- **Analiza obrazów (OCR)** została usunięta z panelu — kontrakt nie definiuje przesyłania obrazów. Backend może natomiast sam analizować zrzuty ekranu pobranych stron modelem VLM (`OLLAMA_VISION_ENABLED`); wyniki trafiają do zwykłych pól `violated_rules` (`AI_VLM_*`) i `evidence_quotes` (`[VLM]`).

---

## 6. Build i konteneryzacja

- **`frontend/Dockerfile`:**
  - Etap `build` (`node:20-alpine`): `yarn install --frozen-lockfile` (warstwa cache'owana po `package.json` + `yarn.lock`), następnie `yarn build` z `GENERATE_SOURCEMAP=false` (kod źródłowy nie jest publikowany w obrazie).
  - Etap końcowy (`nginx:1.27-alpine`): wyłącznie statyczny `build/` + konfiguracja Nginx, `HEALTHCHECK` (`wget` na `/`). Obraz nie zawiera Node.js, `node_modules` ani plików `.env`.
- **`frontend/nginx.conf`:**
  - `location /api/` — proxy do `backend:8000` z nagłówkami `X-Forwarded-*`, `proxy_read_timeout 120s`.
  - `location /ws/` — proxy WebSocket (`Upgrade`/`Connection`), timeout `3600s` dla długotrwałych połączeń alertów.
  - `location /static/` — hashowane assety CRA z `Cache-Control: public, immutable` (1 rok).
  - `location /` — SPA fallback (`try_files ... /index.html`) z `Cache-Control: no-cache`, dzięki czemu bezpośrednie wejście na `/incidents/:id` działa.
  - `client_max_body_size 1m` (treść do analizy ma maks. 20 000 znaków), `gzip`, `server_tokens off`.

---

## 7. Bezpieczeństwo i prywatność

- **Brak telemetrii i skryptów firm trzecich:** z `public/index.html` usunięto PostHog z **nagrywaniem sesji** (wysyłka do `ap.emergent.sh`) oraz skrypt `assets.emergent.sh`; z zależności usunięto `@emergentbase/overlay` i `@emergentbase/visual-edits` (pobierane z serwerów Emergent w czasie builda). Zweryfikowano, że zbudowany bundel nie zawiera odwołań `emergent` / `posthog`.
- **Nagłówki bezpieczeństwa (Nginx):** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` — dołączane snippetem w każdej `location` (dyrektywa `add_header` w `location` nie dziedziczy nagłówków z poziomu `server`).
- **Sekrety:** `frontend/.env` jest ignorowany przez Git i wykluczony z kontekstu builda (`.dockerignore`); w repo jest tylko `frontend/.env.example`. Zmienne `REACT_APP_*` są **publiczne** (trafiają do bundla) — nie wolno w nich umieszczać sekretów.
- **Pozostałe połączenie zewnętrzne:** fonty IBM Plex ładowane z Google Fonts (`fonts.googleapis.com`). Przy wdrożeniu w pełni offline / on-premise należy je hostować lokalnie (np. pakiety `@fontsource/ibm-plex-*`).
- Wyniki audytu zależności: [security-licenses.md](./security-licenses.md#4-wynik-audytu-yarn-audit-frontend).

---

## 8. Uruchomienie i weryfikacja

```bash
# Docker (razem z backendem) — panel: http://localhost:3000
docker compose up --build -d

# Dev lokalny (hot-reload), backend na :8000
cd frontend
cp .env.example .env
yarn install
yarn start
```

**Stan weryfikacji (`2026-11-21`):**
- `docker compose up --build` — oba kontenery `healthy`; `GET /` i ścieżki SPA → `200`; `GET /api/v1/health` przez Nginx → `200`; `/ws/alerts` → `101 Switching Protocols`.
- `yarn start` — `Compiled successfully!`; `CI=true yarn build` — bez ostrzeżeń ESLint.
- Przez Nginx: `POST /api/v1/analyze/text` → incydent zgodny z kontraktem; `POST /api/v1/analyze/url` → `400` dla adresu wewnętrznego (`http://backend:8000/...`), `200` dla publicznej strony; `PATCH /label` zapisuje etykietę.
- **Ręczny test E2E w przeglądarce (zaakceptowany przez zespół):**
  1. Start: `BACKEND ONLINE · WS połączony`, brak paska DEMO, czysta konsola.
  2. Pulpit: KPI i rejestr incydentów, filtr modułów M1/M2/M3, próg alertu w etykiecie KPI.
  3. Karta incydentu: naruszone reguły z podstawą prawną, cytaty i podświetlenia w tekście źródłowym, panel DOM/CSS (Moduł 2), status KNF; zmiana statusu i etykiety przetrwa odświeżenie strony; wydruk A4.
  4. Nowa analiza: przykład tekstowy (wynik + toast przy wysokim ryzyku, brak duplikatu przy ponownej analizie), walidacja braku modułu, URL `http://127.0.0.1/` → komunikat anty-SSRF, URL publiczny → wynik.
  5. Kalibracja: analiza 6 przykładów z etykietami, przeliczanie macierzy i wykresu FP/FN suwakiem.
  6. Live Crawler Log: zdarzenia `crawler_status:*`, `high_risk_alert`, `analysis_complete`, `status_updated`.
  7. Tryb DEMO po `docker compose stop backend` i powrót do online po „Ponów połączenie”.
  8. Przełączanie PL/EN bez surowych kluczy tłumaczeń.
- **Testy automatyczne frontendu:** brak (przygotowane są jedynie stałe `data-testid` w `src/constants/testIds/`).
