# Ryziqo — frontend

Panel analityka UKNF i publiczny formularz obywatela (`/public`) dla systemu Ryziqo. React 19 (Create React App 5 + craco), Tailwind, shadcn/ui, Recharts, d3-force. W Dockerze serwowany przez Nginx, który przekazuje `/api/` i `/ws/` do backendu.

Pełny opis architektury: [docs/frontend-architecture.md](../docs/frontend-architecture.md). Kontrakt API: [CONTRACT.md](../CONTRACT.md).

## Wymagania

- Node.js 20+
- Yarn 1.22 (`corepack enable` albo `npm i -g yarn`)
- Backend na `http://localhost:8000` (bez backendu panel działa w jawnie oznaczonym trybie DEMO)

## Uruchomienie lokalne

```bash
cp .env.example .env
yarn install
yarn start        # http://localhost:3000, hot-reload
```

Całość w Dockerze (z katalogu głównego repozytorium): `docker compose up --build`.

## Skrypty

| Polecenie | Opis |
|---|---|
| `yarn start` | Dev server (craco) na porcie `3000` |
| `yarn build` | Build produkcyjny do `build/`; `CI=true yarn build` traktuje ostrzeżenia ESLint jako błędy |
| `yarn test` | Jest (CRA) — obecnie brak testów |
| `yarn audit` | Audyt zależności (wyniki: [docs/security-licenses.md](../docs/security-licenses.md)) |

## Zmienne środowiskowe

Wklejane do bundla w czasie **builda** — po zmianie zrestartuj `yarn start` / przebuduj obraz. Nie umieszczaj w nich sekretów.

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `REACT_APP_INVESTWATCH_API_URL` | `http://localhost:8000/api/v1` | Adres API; w Dockerze `/api/v1` (proxy Nginx) |
| `REACT_APP_ALERT_THRESHOLD` | `0.7` | Próg `risk_score` dla toastów i KPI „wysokie ryzyko” |
| `ENABLE_HEALTH_CHECK` | `false` | Endpointy zdrowia dev servera |

## Widoki

| Ścieżka | Opis |
|---|---|
| `/` | Pulpit: KPI, trend, live log, przegląd zagrożeń, rejestr incydentów z eksportem CSV/JSON |
| `/public` | Formularz obywatela: tekst / URL / zrzut ekranu, wybór zgody na udostępnienie |
| `/analyze` | Nowa analiza z postępem na żywo (SSE) i anulowaniem |
| `/incidents/:id` | Karta incydentu: reguły, cytaty, wersje strony, klony, paczka dowodowa ZIP, druk A4 |
| `/reports`, `/reports/:id` | Baza zgłoszeń i ocena analityka |
| `/campaigns` | Kampanie (grupy powiązanych zgłoszeń) |
| `/graph` | Mapa powiązań |
| `/diagnostics` | Stan modelu Ollama i kolejki analiz |
| `/calibration` | Kalibracja progu (macierz TP/FP/TN/FN) |
| `/log` | Pełny dziennik zdarzeń |

## Struktura

```text
src/
├── App.js          routing
├── pages/          widoki (tabela wyżej)
├── components/     Header/Sidebar, DemoBanner, IncidentTable, TrendChart, LiveLog, Badges, ErrorBoundary; ui/ = shadcn/ui (slider, sheet)
└── lib/            config, api (REST + SSE), store (stan globalny), demoEngine, i18n, samples, exportRegister
```

Konwencje (i18n, `data-testid`, dodawanie widoku lub wywołania API): [docs/frontend-architecture.md §10](../docs/frontend-architecture.md#10-konwencje-i-rozwój).
