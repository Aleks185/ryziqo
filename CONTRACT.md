# #InvestWatch — Zamrożony Kontrakt API i WebSocket (`CONTRACT.md`)

**Wersja:** `1.2.0` (HackNation UKNF 2026) — rozszerzenia addytywne względem `1.0.0` (nowe endpointy, bez zmian istniejących pól i ścieżek; zob. [Historia zmian](#5-historia-zmian))  
**Zasada współpracy:** Po zamrożeniu nie zmieniamy jednostronnie nazw pól, typów ani ścieżek. Ewentualne rozszerzenia wyłącznie jako opcjonalne pola po obustronnej zgodzie.

---

## 1. Bazowe adresy

- **Backend (dev lokalny):** `http://localhost:8000`
- **Backend (Docker przez Nginx proxy frontendu):** ścieżki relatywne `/api/v1/...` oraz `/ws/alerts`
- **Swagger / OpenAPI:** `http://localhost:8000/docs`

---

## 2. Model danych `Incident`

Każdy rekord zwracany przez API i agregator wyników Modułów 1–3 ma ujednoliconą strukturę:

```json
{
  "id": "inc_20261121_001",
  "module_id": 2,
  "module_name": "Weryfikacja zgodności i informacji o ryzyku",
  "entity_name": "Alpha CFD Broker S.A.",
  "promoter_name": null,
  "knf_registry_status": "registered_pl",
  "source_platform": "web",
  "source_url": "mock://broker_promo_hidden_risk.html",
  "title": "Zarabiaj nawet 40% rocznie na kontraktach CFD bez prowizji!",
  "content_excerpt": "Otwórz rachunek w 2 minuty i zyskuj do 40% rocznie...",
  "evidence_quotes": [
    "Zyskaj nawet 40% rocznie — sprawdzone wyniki naszych klientów!",
    "Kontrakty CFD są złożonymi instrumentami... (ukryte w stopce 8px, kontrast 2.1:1)"
  ],
  "violated_rules": [
    {
      "rule_id": "3",
      "rule_name": "Informacja o ryzyku",
      "legal_basis": "art. 44 ust. 2 lit. b rozporządzenia del. 2017/565",
      "severity": "high",
      "reason": "Twierdzenia o wysokich zyskach bez równorzędnego ostrzeżenia o ryzyku."
    }
  ],
  "dom_metrics": {
    "dominant_font_px": 18.0,
    "risk_font_px": 8.0,
    "font_ratio": 0.44,
    "risk_hidden_in_footer": true,
    "requires_click_to_view_risk": false,
    "low_contrast_detected": true,
    "responsive_overflow_detected": false
  },
  "risk_score": 0.89,
  "risk_level": "high",
  "status": "new",
  "analyst_note": null,
  "ground_truth_label": true,
  "model_used": "gemma3:4b + uknf-rules-v1",
  "is_demo_fallback": false,
  "content_hash": "a3f19c...",
  "storage_key": "a3f19c....json",
  "detected_at": "2026-11-21T12:15:00Z",
  "updated_at": "2026-11-21T12:15:00Z"
}
```

### Słowniki wartości
- `module_id`: `1` (Finfluencerzy i podmioty trzecie) | `2` (Zgodność i informacja o ryzyku — 18 reguł UKNF) | `3` (Shadow Advisory — art. 76 u.o.i.f.)
- `knf_registry_status`: `"registered_pl"` | `"registered_eu_branch"` | `"registered_eu_crossborder"` | `"not_in_knf_snapshot"` | `"unknown"`
- `source_platform`: `"web"` | `"facebook"` | `"instagram"` | `"tiktok"` | `"youtube"` | `"mock_demo"` | `"manual"` *(od 1.1.0 — treść wklejona przez analityka)* | `"x"` *(od 1.2.0)*
- `risk_score`: liczba zmiennoprzecinkowa **`0.00` – `1.00`** (wskaźnik modelu AI + reguł; nie stanowi wiążącego rozstrzygnięcia prawnego).
- `risk_level`: `"low"` (`< 0.40`) | `"medium"` (`0.40 – 0.69`) | `"high"` (`>= 0.70`) — domyślna etykieta; **Panel Kalibracji w UI przelicza flagowanie dynamicznie wg suwaka `threshold`**.
- `status`: `"new"` | `"in_review"` | `"confirmed"` | `"false_positive"` | `"dismissed"`
- `ground_truth_label`: `true` (rzeczywiste naruszenie referencyjne) | `false` (materiał poprawny / neutralny) | `null` (brak etykiety referencyjnej). Służy do wyliczania macierzy **TP / FP / TN / FN** w Panelu Kalibracji.

---

## 3. Endpointy REST

### `GET /api/v1/health`
Status serwisu, dostępność Ollama na hoście, tryb pracy (`live` vs `demo_fallback`) oraz data lokalnego snapshotu KNF.
```json
{
  "status": "ok",
  "ollama_available": false,
  "ollama_model": "gemma3:4b",
  "mode": "demo_fallback",
  "knf_snapshot_date": "2026-11-21",
  "knf_snapshot_note": "Lokalny snapshot demonstracyjny — nie zastępuje bieżącej weryfikacji w rejestrach KNF.",
  "incidents_count": 14,
  "scheduler_running": true
}
```

### `GET /api/v1/incidents`
Zwraca listę incydentów z opcjonalnym filtrowaniem.
- Query params (wszystkie opcjonalne):
  - `module_id`: `1` | `2` | `3`
  - `source_platform`: string (np. `tiktok`, `instagram`, `web`)
  - `status`: `new` | `in_review` | `confirmed` | `false_positive` | `dismissed`
  - `risk_level`: `low` | `medium` | `high` *(od 1.2.0)*
  - `min_risk_score`: float (`0.0`–`1.0`)
  - `max_risk_score`: float (`0.0`–`1.0`)
  - `date_from`: ISO-8601 (np. `2026-11-15T00:00:00Z`)
  - `date_to`: ISO-8601
  - `search`: pełnotekstowe szukanie po nazwie podmiotu, tytule, URL i cytatach
  - `limit`: int (domyślnie `100`, max `500`)
  - `offset`: int (domyślnie `0`)
- Odpowiedź:
```json
{
  "items": [ /* Incident[] */ ],
  "total": 14,
  "knf_snapshot_date": "2026-11-21",
  "mode": "demo_fallback"
}
```

### `GET /api/v1/incidents/{incident_id}`
Zwraca pojedynczy obiekt `Incident` wraz z `raw_text_preview`.

### `PATCH /api/v1/incidents/{incident_id}/status`
Aktualizuje status incydentu w SQLite i rozgłasza zdarzenie `status_updated` przez WebSocket.
- Request body:
```json
{
  "status": "confirmed",
  "analyst_note": "Potwierdzono brak ostrzeżenia o ryzyku przy obietnicy zysku."
}
```
- Response: zaktualizowany obiekt `Incident`.

### `PATCH /api/v1/incidents/{incident_id}/label` *(od 1.1.0)*
Ustawia etykietę referencyjną analityka używaną w kalibracji progu (TP/FP/TN/FN) i rozgłasza `status_updated` (z `extra.ground_truth_label`).
- Request body: `{ "ground_truth_label": true }` — dopuszczalne `true` | `false` | `null` (usunięcie etykiety).
- Response: zaktualizowany obiekt `Incident`. `404`, gdy incydent nie istnieje.

### `GET /api/v1/stats`
Zwraca zagregowane metryki do KPI i wykresów trendów (Recharts/Chart.js).
- Query param: `threshold` (float, domyślnie `0.50`)
- Odpowiedź:
```json
{
  "threshold": 0.5,
  "total_incidents": 14,
  "flagged_count": 10,
  "by_module": { "1": 4, "2": 6, "3": 4 },
  "by_source": { "web": 8, "tiktok": 2, "instagram": 2, "facebook": 2 },
  "by_status": { "new": 11, "in_review": 2, "confirmed": 1 },
  "trend_by_day": [
    { "date": "2026-11-18", "total": 2, "flagged": 1, "high_risk": 1 },
    { "date": "2026-11-21", "total": 6, "flagged": 5, "high_risk": 4 }
  ],
  "top_violated_rules": [
    { "rule_id": "3", "rule_name": "Informacja o ryzyku", "count": 4 }
  ],
  "calibration": {
    "threshold": 0.5,
    "labeled_total": 14,
    "tp": 9,
    "fp": 1,
    "tn": 3,
    "fn": 1,
    "precision": 0.9,
    "recall": 0.9,
    "f1_score": 0.9
  }
}
```

### `POST /api/v1/crawl/trigger`
Dodaje zadanie scrapowania i analizy do kolejki zadań backendu.
- Request body:
```json
{
  "mode": "mock_all",
  "target_url": null,
  "mock_file": null,
  "module_ids": [1, 2, 3],
  "use_playwright": false
}
```
  - `mode`: `"mock_all"` (skanuje wszystkie lokalne strony demonstracyjne), `"mock_single"` (wymaga `mock_file`, np. `"broker_promo_hidden_risk.html"`), `"public_url"` (wymaga `target_url` — przechodzi walidację anty-SSRF!).
- Odpowiedź (`202 Accepted`):
```json
{
  "job_id": "job_20261121_abc123",
  "status": "queued",
  "mode": "mock_all",
  "message": "Zadanie dodane do kolejki analizy."
}
```

### `POST /api/v1/analyze/text` *(od 1.1.0)*
Synchroniczna analiza treści wklejonej przez analityka (reklama, post, opis wideo) tym samym pipeline'em co kolejka (Moduły 1–3, deduplikacja po `content_hash`, alerty WS).
- Request body:
```json
{
  "content": "XTradePro — handluj kontraktami CFD z dźwignią 1:500! ...",
  "title": "Reklama CFD z Instagrama",
  "source_url": "manual://sample/S2",
  "module_ids": [1, 2, 3],
  "ground_truth_label": null
}
```
  - `content`: wymagane, `20`–`20000` znaków. Treść jest escapowana — znaczniki HTML traktowane są jako tekst.
  - `title`, `source_url` (etykieta pochodzenia, **nie jest pobierana**; domyślnie `"manual://text"`), `ground_truth_label`: opcjonalne.
  - `module_ids`: niepusta lista z `1` | `2` | `3` (domyślnie wszystkie).
- Odpowiedź (`200`):
```json
{
  "items": [ /* Incident[] z polem raw_text_preview */ ],
  "mode": "demo_fallback"
}
```
  - Ponowna analiza identycznej treści aktualizuje istniejący incydent (zachowuje `status`, `analyst_note`, `ground_truth_label`).
  - Po zakończeniu serwer rozgłasza `analysis_complete` z `extra.incident_ids`.

### `POST /api/v1/analyze/url` *(od 1.1.0)*
Synchroniczne pobranie **jednego publicznego URL** (walidacja anty-SSRF na każdym przekierowaniu, limity rozmiaru i przekierowań) i jego analiza.
- Request body: `{ "url": "https://example.com/promo", "module_ids": [1, 2, 3], "use_playwright": false }`
- Odpowiedź (`200`): jak w `POST /api/v1/analyze/text`.
- Błędy: `400` — adres odrzucony przez anty-SSRF (localhost, sieci prywatne, metadata, niedozwolony schemat); `502` — nie udało się pobrać strony (timeout, błąd HTTP, nieobsługiwany typ treści, przekroczony limit rozmiaru); `422` — niepoprawne dane wejściowe.

> Analiza obrazów (OCR) nie jest częścią kontraktu — backend nie zawiera silnika OCR; panel nie oferuje tej funkcji.

### `GET /api/v1/crawl/jobs`
Zwraca listę zadań kolejki, dostępnych plików mock-demo oraz najbliższy termin uruchomienia APScheduler.

### Watchlista — okresowo skanowane źródła *(od 1.2.0)*
Publiczne adresy (np. profile finfluencerów) skanowane przez harmonogram razem z mock-stronami demo.
- `GET /api/v1/watchlist` → `{"items": WatchTarget[], "schedule": "interval: 15 min" | "cron: */30 * * * * (UTC)" | "disabled", "scheduler_next_run": "ISO-8601" | null}`
- `POST /api/v1/watchlist` z `{"url": "https://...", "label": "opcjonalnie", "module_ids": [1,2,3], "use_playwright": false}` → `201 WatchTarget`; `400` dla adresu zablokowanego przez anty-SSRF, `409` gdy URL już jest na liście.
- `PATCH /api/v1/watchlist/{id}` z `{"enabled": true | false}` → `200 WatchTarget`; `404` dla nieistniejącego ID.
- `DELETE /api/v1/watchlist/{id}` → `204`; `404` dla nieistniejącego ID.
- `POST /api/v1/watchlist/run` → `202 {"job_ids": [...], "skipped": [...]}` — natychmiastowe uruchomienie skanu harmonogramu; cele już przetwarzane trafiają do `skipped`.

`WatchTarget`: `{"id": 1, "url": "https://...", "label": null, "module_ids": [1,2,3], "use_playwright": false, "enabled": true, "created_at": "ISO-8601", "last_enqueued_at": "ISO-8601" | null}`

### `GET /api/v1/reports/{module_id}` *(od 1.2.0)*
Raport modułu (`1`–`3`): dane firmy inwestycyjnej, dane podmiotu reklamującego, treść i dokładny URL.
- Query params (opcjonalne): `format` (`json` domyślnie | `csv`), `min_risk_score`, `status`, `date_from`, `date_to`.
- `json`: `{"module_id", "module_name", "generated_at", "knf_snapshot_date", "total", "items": [...]}`.
- `csv`: UTF-8 z BOM, separator `;`, nagłówek `Content-Disposition: attachment`; listy (`evidence_quotes`, `violated_rule_ids`) łączone ` | `; komórki zaczynające się od `=`, `+`, `-`, `@` poprzedzone `'` (ochrona przed CSV injection).
- Kolumny: `id, detected_at, updated_at, risk_score, risk_level, status, entity_name, knf_registry_status, promoter_name, source_platform, source_url, title, content_excerpt, evidence_quotes, violated_rule_ids, analyst_note`.

### `GET /api/v1/knf-registry` & `GET /api/v1/rules`
- `/api/v1/knf-registry`: lokalny snapshot podmiotów KNF (data, źródła URL z załączników UKNF, lista podmiotów).
- `/api/v1/rules`: pełna lista 18 reguł UKNF z załącznika do Modułu 2 wraz z podstawami prawnymi.

---

## 4. Kontrakt WebSocket (`GET /ws/alerts`)

Połączenie: `ws://localhost:8000/ws/alerts` (lub `wss://.../ws/alerts` przez proxy).  
Klient może wysyłać opcjonalny tekst `"ping"` → serwer odpowiada `{"type": "pong", "timestamp": "..."}`.

Format komunikatów serwera:
```json
{
  "type": "connected" | "crawler_status" | "high_risk_alert" | "analysis_complete" | "status_updated" | "error",
  "timestamp": "2026-11-21T13:15:02Z",
  "job_id": "job_20261121_abc123",
  "stage": "queued" | "fetching" | "preprocessing" | "analyzing" | "completed" | "error",
  "source": "mock://broker_promo_hidden_risk.html",
  "module_id": 2,
  "incident_id": "inc_20261121_001",
  "risk_score": 0.89,
  "message": "Wykryto wysokie ryzyko (0.89) w Module 2: Alpha CFD Broker S.A."
}
```

---

## 5. Historia zmian

| Wersja | Zmiany |
|---|---|
| `1.2.0` | Filtr `risk_level` w `GET /api/v1/incidents`; endpointy `/api/v1/watchlist*` i `GET /api/v1/reports/{module_id}`; nowa wartość `source_platform: "x"`. Bez zmian istniejących pól, typów i ścieżek. |
| `1.1.0` | Dodane endpointy `POST /api/v1/analyze/text`, `POST /api/v1/analyze/url`, `PATCH /api/v1/incidents/{incident_id}/label`; nowa wartość `source_platform: "manual"`; `analysis_complete` może zawierać `extra.incident_ids`. Bez zmian istniejących pól, typów i ścieżek. |
| `1.0.0` | Zamrożenie kontraktu: model `Incident`, REST (`/health`, `/incidents`, `/status`, `/stats`, `/crawl/*`, `/knf-registry`, `/rules`), WebSocket `/ws/alerts`. |
