# INVESTWATCH — kontrakt API frontend ↔ backend

> **Status: DRAFT** — do wspólnego zamrożenia przez Krzysztofa (frontend) i Aleksa (backend + scraper + Ollama).
> Frontend dostosuje się do zmian; każdą zmianę wpisujemy w sekcji *Changelog* na dole.

## 1. Adresy i konfiguracja

| Element | Wartość domyślna | Zmienna |
|---|---|---|
| REST base | `http://localhost:8000/api/v1` | `VITE_API_URL` (Vite) / `REACT_APP_INVESTWATCH_API_URL` (podgląd Emergent, CRA) |
| WebSocket | `ws://localhost:8000/ws/alerts` | wyliczany automatycznie z REST base (`http→ws`, `https→wss`, obcięcie `/api/v1`) |
| Próg toastów | `0.70` | `REACT_APP_ALERT_THRESHOLD` / `VITE_ALERT_THRESHOLD` |

- Komunikacja odbywa się **z przeglądarki** (nie z kontenera frontendu), więc w Docker Compose adres to `localhost:8000`, nie nazwa serwisu.
- Backend musi zwracać CORS dla `http://localhost:5173` (Vite dev) i adresu produkcyjnego frontendu.
- Strona HTTPS nie połączy się z backendem `http://` (mixed content) — frontend wtedy od razu przechodzi w tryb DEMO, bez prób połączenia.

## 2. Model `Incident`

```json
{
  "id": "inc_lx9a2k3f",
  "created_at": "2026-06-14T10:21:07.512Z",
  "source_type": "text",
  "source_url": null,
  "content": "Dołącz do grupy VIP na Telegramie — tylko 199 zł miesięcznie. Dzisiejszy sygnał: kupuj BTC…",
  "modules": ["M1", "M2", "M3"],
  "risk_score": 0.74,
  "module_scores": { "M1": 0.0, "M2": 0.0, "M3": 0.74 },
  "primary_module": "M3",
  "reasoning": "Materiał zawiera konkretne rekomendacje kupna z poziomami TP/SL oraz płatny dostęp do sygnałów…",
  "findings": [
    { "module": "M3", "rule_id": "m3_levels", "weight": 0.3 }
  ],
  "quotes": [
    { "text": "Dzisiejszy sygnał: kupuj BTC, cena wejścia 61 500 USD, take profit 64 000, stop loss 60 200.", "start": 62, "end": 155, "modules": ["M3"], "rules": ["m3_levels"] }
  ],
  "entity": {
    "name": "FxSignals Capital",
    "registry_status": "not_found",
    "registry_source": "Lista ostrzeżeń publicznych KNF",
    "checked_at": "2026-06-14T10:21:09.000Z"
  },
  "status": "new",
  "ground_truth": null,
  "sample_id": null,
  "content_hash": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "analysis_engine": "ollama:llama3.1:8b",
  "is_demo": false
}
```

| Pole | Typ | Uwagi |
|---|---|---|
| `risk_score` | float `0.00–1.00` | zaokrąglony do 2 miejsc; = max z `module_scores` (lub decyzja modelu) |
| `module_scores` | `{M1?,M2?,M3?}` | tylko dla modułów z `modules` |
| `primary_module` | `"M1"｜"M2"｜"M3"｜null` | `null` gdy brak sygnałów |
| `reasoning` | string ｜ null | uzasadnienie z LLM; `null` → frontend buduje opis z `findings` |
| `findings` | array (opcjonalne) | `rule_id` dowolny string; nieznane ID frontend pokazuje surowo |
| `quotes[].text` | string | **dosłowny** fragment `content`; `start/end` = offsety znaków w `content` (opcjonalne, wtedy brak podświetlenia) |
| `entity.registry_status` | `"not_checked"｜"authorized"｜"not_found"｜"warning_list"` | sprawdzenie rejestrów KNF wyłącznie po stronie backendu |
| `status` | `"new"｜"in_review"｜"confirmed"｜"dismissed"` | |
| `ground_truth` | bool ｜ null | etykieta referencyjna do kalibracji |
| `content_hash` | hex SHA-256 | z treści (dla obrazu — z tekstu po OCR lub z pliku) |
| `source_type` | `"text"｜"url"｜"image"` | |

Moduły: **M1** Finfluencerzy i podmioty trzecie · **M2** Zgodność informacji o ryzyku · **M3** Shadow Advisory.

## 3. Endpointy REST

| Metoda | Ścieżka | Body | Odpowiedź |
|---|---|---|---|
| GET | `/health` | — | `{ "status": "ok", "ollama": true, "version": "0.1.0" }` (timeout frontu: 2,5 s) |
| GET | `/incidents?limit=500` | — | `{ "items": Incident[], "total": 42 }` (sort malejąco po `created_at`) |
| GET | `/incidents/{id}` | — | `Incident` |
| POST | `/analyze/text` | `{ "content": str, "modules": ["M1","M3"], "sample_id"?: str, "ground_truth"?: bool }` | `Incident` (201) |
| POST | `/analyze/url` | `{ "url": str, "modules": [...] }` | `Incident` (`source_url` wypełnione, `content` = zescrapowany tekst) |
| POST | `/analyze/image` | `multipart/form-data`: `file` (PNG/JPEG/WebP, ≤ 10 MB), `modules` = `"M1,M2,M3"` | `Incident` (`source_type: "image"`, `content` = tekst OCR) |
| PATCH | `/incidents/{id}/status` *(opcjonalny)* | `{ "status": "in_review" }` | `Incident` |
| PATCH | `/incidents/{id}/label` *(opcjonalny)* | `{ "ground_truth": true }` | `Incident` |

Błędy: kod HTTP ≥ 400 + `{ "detail": "opis" }`. Brak endpointów opcjonalnych (404/405) → frontend zapisuje zmianę lokalnie z etykietą „DEMO”.
Timeout analizy po stronie frontu: 60 s (Ollama lokalnie bywa wolna).

## 4. WebSocket `/ws/alerts`

Serwer → klient, JSON:

```json
{ "type": "incident.created", "ts": "2026-06-14T10:21:07Z", "data": { /* Incident */ } }
{ "type": "incident.updated", "ts": "…", "data": { /* Incident */ } }
{ "type": "crawler.progress", "ts": "…", "data": { "source": "tiktok:#inwestowanie", "processed": 120, "total": 500 } }
{ "type": "crawler.error",    "ts": "…", "data": { "source": "youtube", "message": "rate limit" } }
{ "type": "heartbeat",        "ts": "…", "data": {} }
```

- Frontend łączy WS **tylko**, gdy `/health` odpowiedział. Reconnect: backoff 2/4/8/16/32 s, potem stan „offline” (bez pętli błędów w konsoli).
- `incident.created` z `risk_score >= 0.70` → toast (deduplikacja po `id`).
- `heartbeat` co 20–30 s, nie jest logowany.

## 5. Tryb DEMO (frontend)

Gdy backend nieosiągalny: wbudowany w przeglądarkę analizator regułowy (`src/lib/demoEngine.js`) realizuje ten sam model `Incident`, zapis w `localStorage`, `analysis_engine: "demo-heuristic-v1"`, `is_demo: true`, `entity.registry_status: "not_checked"`. Każdy wynik oznaczony „DEMO — heurystyka, nie AI”. URL i OCR w DEMO są wyłączone.

## 6. AI-Driven Development Workflow

1. **Kontrakt najpierw.** Ten plik jest jedynym źródłem prawdy. Prompty do asystentów AI (Emergent, Copilot, Claude, itp.) zawsze zawierają aktualny `CONTRACT.md`.
2. **Frontend** (Krzysztof): budowany i rozwijany z asystentem AI w Emergent; tryb DEMO pozwala pracować bez backendu.
3. **Backend** (Aleks): FastAPI + SQLite + scraper + Ollama (lokalnie, bez płatnych usług AI). Prompt systemowy LLM wymusza zwrot JSON zgodnego z modelem `Incident` i cytaty **dosłowne** z `content` (backend weryfikuje `content.find(quote.text)` i odrzuca/naprawia cytaty niedosłowne).
4. **Weryfikacja człowieka.** Kod wygenerowany przez AI przechodzi przegląd drugiej osoby; wyniki AI w aplikacji są wskazówką dla analityka, nie oceną prawną.
5. **Zmiany kontraktu:** PR zmieniający `CONTRACT.md` + wpis w Changelog + ping do drugiej osoby. Po feature freeze — tylko poprawki.
6. **Testy integracyjne:** 6 próbek z `src/lib/samples.js` (z `ground_truth`) wysyłamy na `/analyze/text`; panel kalibracji pokazuje TP/FP/FN/TN dla modelu Aleksa.

## 7. Uruchomienie lokalne (cel Fazy 2)

```
docker compose up        # backend :8000, frontend :5173 / :80
VITE_API_URL=http://localhost:8000/api/v1
```

## Changelog
- 2026-06 — DRAFT v0.1 (Emergent/Krzysztof).
