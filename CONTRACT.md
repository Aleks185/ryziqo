# Ryziqo — Zamrożony Kontrakt API i WebSocket (`CONTRACT.md`)

**Wersja:** `1.4.0` (HackNation UKNF 2026) — rozszerzenia addytywne względem `1.0.0` (nowe endpointy, bez zmian istniejących pól i ścieżek; zob. [Historia zmian](#5-historia-zmian))  
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
- `violated_rules[].rule_id`: identyfikatory kryteriów UKNF `"1"`–`"18"` (w tym `"12a"`, `"12b"`) oraz reguły modułów (`M1_*`, `M3_*`). Rozszerzenie addytywne (bez zmiany schematu): sygnały semantyczne LLM potwierdzone cytatem (`AI_*`, np. `AI_M3_SUCCESS_FEE`, `AI_PROMPT_INJECTION`), sygnały VLM (`AI_VLM_*`), `CAMPAIGN_CLONE_MATCH`, `KNF_WARNING_LIST_MATCH`, `KNF_IMPERSONATION_SUSPECT`, *(od 1.4.0)* `RISK_WARNING_REMOVED` (ostrzeżenie o ryzyku usunięte lub zmniejszone względem poprzedniej wersji strony). Klient powinien traktować nieznane `rule_id` jako zwykłe naruszenie.
- `violated_rules[].related_incident_ids` *(addytywne, domyślnie `[]`)*: identyfikatory incydentów, na które wskazuje reguła — dla `CAMPAIGN_CLONE_MATCH` potwierdzone oryginały kampanii (krawędzie `clone_of` na mapie powiązań).
- `evidence_quotes[]`: dosłowne cytaty z treści; wpisy techniczne mają prefiks `[AI]`, `[AI-Context]`, `[AI-Guard]`, `[VLM]`, `[KNF]`, `[Klon]`, `[Wtórne]`.
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
- *(od 1.4.0)* Dodatkowe pola `IncidentDetail`: `prompt_injection_snippets: string[]` (wykryte polecenia dla systemu oceny), `hidden_text_snippets: string[]` (tekst niewidoczny dla użytkownika, wyłączony z analizy) oraz `quote_checks: [{"quote", "match"}]`, gdzie `match` ∈ `exact` | `fuzzy` | `missing` | `system` (wynik strażnika anty-halucynacyjnego; `system` = wpis techniczny z prefiksem `[`).

### `GET /api/v1/incidents/{incident_id}/similar` *(od 1.4.0)*
Do 5 (`limit` 1–20) incydentów zweryfikowanych przez analityka (etykieta lub status `confirmed` / `false_positive`), najbliższych treściowo; ta sama pula i próg (≥ 0,45) co dynamiczne przykłady few-shot (RAG).
- Element: `{"incident_id", "module_id", "title", "source_url", "similarity", "label", "status", "analyst_note", "is_clone"}`; `is_clone` = potwierdzone naruszenie na innej domenie z podobieństwem ≥ `AI_CLONE_SIMILARITY_THRESHOLD`.

### `GET /api/v1/incidents/{incident_id}/versions` *(od 1.4.0)*
Historia zapisanych wersji adresu incydentu (najstarsza pierwsza): `{"versions": [{"content_hash", "fetched_at", "has_risk_warning", "risk_font_px", "is_current"}], "last_change": null | {"from", "to", "warning_change": null | "removed" | "shrunk", "removed": string[], "added": string[]}}` (zdania usunięte i dodane między dwiema ostatnimi wersjami).

### `GET /api/v1/incidents/{incident_id}/evidence-pack` *(od 1.4.0)*
Plik `application/zip` (`evidence_pack_<id>.zip`): `source.html`, `extraction.json`, `screenshots/*`, `incident.json`, `report.json` (najnowsze zgłoszenie z bazy zgłoszeń, jeśli istnieje), `versions.json`, `manifest.json` (SHA-256 i rozmiar każdego pliku), `manifest.sha256`, opcjonalnie `manifest.tsr` (znacznik czasu RFC 3161 dla `manifest.json`, gdy ustawiono `EVIDENCE_TSA_URL`; błąd TSA trafia do `manifest.notes`). `404` dla nieznanego incydentu.

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
- *(od 1.4.0)* Pole `verified_decisions`: liczba decyzji analityków (etykieta lub status `confirmed` / `false_positive`) wykorzystywanych przez RAG.
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
  - *(od 1.3.0, opcjonalne)* `origin`: `"manual"` (domyślnie) | `"watchlist"` | `"discovery"` | `"seed"` | `"link_follow"`; `follow_depth` (0–2, domyślnie 0) i `follow_max_pages` (1–30, domyślnie 10) — chodzenie po podstronach tej samej domeny dla `public_url`.
  - *(od 1.3.0)* `409` gdy ten sam cel (URL po kanonikalizacji) jest już w kolejce lub w trakcie analizy. Strona zablokowana przez `robots.txt` kończy zadanie statusem `completed` z `error_message: "robots.txt disallow"`.
  - `CrawlJobRecord` w `GET /api/v1/crawl/jobs` ma od 1.3.0 pole `origin`.
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
  - *(od 1.4.0, wszystkie endpointy analizy)* `share_mode`: `null` (domyślnie, dotychczasowe zachowanie) | `"none"` (tylko werdykt: nic nie jest zapisywane, brak alertów WS i wpisu w bazie zgłoszeń) | `"anonymous"` (zapis bez IP, User-Agent i skrótu IP zgłaszającego) | `"signed"` (wymaga `reporter_display_name` do 40 znaków i `reporter_key` — losowego klucza przeglądarki, przechowywanego wyłącznie jako HMAC; `422` przy braku). Dla `source_channel: "public_form"` numery PESEL i kart płatniczych (z poprawną sumą kontrolną) są maskowane przed analizą.
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
- Błędy: `400` — adres odrzucony przez anty-SSRF (localhost, sieci prywatne, metadata, niedozwolony schemat); `502` — nie udało się pobrać strony (błąd HTTP, nieobsługiwany typ treści, przekroczony limit rozmiaru); `504` — timeout; `422` — niepoprawne dane wejściowe.

### Analiza zrzutów i postęp zadań

Ten sam endpoint tekstowy przyjmuje również obiekt z polem `image_base64`, opcjonalnym `title` i listą `module_ids`. Obraz PNG, JPEG lub WebP może mieć do 10 MiB i 20 milionów pikseli. Model wizyjny odczytuje treść obrazu. *(od 1.4.0)* Gdy model wizyjny jest niedostępny, tekst odczytuje lokalny OCR (RapidOCR), a `report.limitations` zawiera informację, że logotypy nie były oceniane; `503` tylko wtedy, gdy nie działa ani model wizyjny, ani OCR.

Obok `items` i `mode` odpowiedź zawiera `report` z polami `source_type`, `status`, `summary`, `findings`, `limitations` i `requires_human_review`. W raporcie `risk_score` jest liczbą całkowitą od 0 do 100. Incydenty w `items` nadal używają skali 0–1.

- `POST /api/v1/analyze/jobs` przyjmuje jeden z tych samych obiektów wejściowych (tekst, URL lub obraz) i zwraca `202` z `job_id`. Pełna kolejka zwraca `429`.
- `GET /api/v1/analyze/jobs/{job_id}/events` zwraca SSE z numerowanymi zdarzeniami `queued`, `status`, `token`, `completed` i `error`. Pole `data` zawiera JSON. Zdarzenie `completed` przekazuje pełną odpowiedź analizy. Nagłówek `Last-Event-ID` umożliwia wznowienie strumienia w granicach bufora zadania.
- `DELETE /api/v1/analyze/jobs/{job_id}` anuluje zadanie. Rozłączenie odbiorcy SSE pozwala ponownie podłączyć się do działającego zadania. Zadania są lokalne dla pojedynczego procesu API.


### Baza zgłoszeń, kampanie i diagnostyka (`/api/v1/intelligence/*`)

Każda analiza (z wyjątkiem `share_mode: "none"`) zapisuje wpis w bazie zgłoszeń (`threat_reports`). Wpisy z identycznym odciskiem (hash treści, pHash obrazu, domena / URL) dostają wspólny `campaign_id`. `risk_score` wpisu jest w skali **0–100** (jak w `report`), incydenty nadal używają 0–1.

- `GET /api/v1/intelligence/reports` — parametry: `q` (do 240 znaków; szuka w domenie, fragmencie treści, IP serwera, podmiotach i URL), `verdict`, `campaign`, `incident` (wpisy powiązane z incydentem), `limit` (1–200, domyślnie 50), `offset`. Odpowiedź: `{"total", "items": [{"id", "created_at", "source_channel", "reporter_display_name", "source_type", "target_url", "canonical_domain", "platform", "target_server_ip", "campaign_id", "detected_entities", "risk_score", "verdict_status", "excerpt", "origin", "incident_ids"}]}` (od najnowszych).
- `GET /api/v1/intelligence/reports/{report_id}` — pełny wpis, m.in. `redirect_chain`, `hosting_asn`, `hosting_country`, `content_hash`, `image_phash`, `analyst_notes`, `ai_report_json` (`summary`, `findings[].reasons`, `findings[].evidence`, `limitations`). Identyfikatory zgłaszającego (IP, skrót IP, User-Agent, HMAC klucza) nie są zwracane. `404` dla nieznanego wpisu.
- `PATCH /api/v1/intelligence/reports/{report_id}` — `{"verdict_status"?, "analyst_notes"? (≤ 4000 znaków)}`; zwraca zaktualizowany wpis. `422` bez zmian, `404` dla nieznanego wpisu.
- `GET /api/v1/intelligence/campaigns` — grupy co najmniej 2 wpisów: `[{"campaign_id", "members", "risk_score", "domain", "server_ip", "last_seen"}]`.
- `PATCH /api/v1/intelligence/campaigns/{campaign_id}` — `{"verdict_status"}` dla wszystkich wpisów grupy; zwraca `{"updated": <liczba>}`. `422` bez statusu, `404` dla nieznanej kampanii.
- `GET /api/v1/intelligence/diagnostics` — `{"total", "confirmed", "campaigns", "cache_hits", "fast_hits", "saved_seconds", "active", "waiting", "capacity", "model", "available"}` (liczniki bazy zgłoszeń, stan kolejki analiz i modelu Ollama).

Słowniki: `verdict_status` ∈ `new` | `confirmed_fake` | `requires_review` | `false_positive` (niezależny od `Incident.status`); `origin` / `report.result_origin` ∈ `fast_path` (dopasowanie do potwierdzonego fake'a, bez LLM) | `cache` | `ollama` | `rules` | `history`.

### `GET /api/v1/intelligence/graph` *(od 1.4.0)*
Mapa powiązań incydentów (`min_score` 0–1, domyślnie `0.5`; `limit` do 500): `{"nodes": [{"id", "type", "label", "weight", ...}], "edges": [{"source", "target", "type"}], "truncated"}`. Typy węzłów: `incident`, `promoter`, `entity`, `domain`, `link_domain`, `referral_code`, `campaign`, `warning_list`; krawędzie: `published_on`, `promotes`, `advertises`, `links_to`, `uses_code`, `in_campaign`, `on_warning_list`, `clone_of`. Węzły pomocnicze połączone tylko z jednym incydentem (domeny, linki, kody) są pomijane. Wpisy bazy zgłoszeń mają od 1.4.0 pole `reporter_display_name` (pseudonim przy zgłoszeniu podpisanym).

### `GET /api/v1/crawl/jobs`
Zwraca listę zadań kolejki, dostępnych plików mock-demo oraz najbliższy termin uruchomienia APScheduler.

### Watchlista — okresowo skanowane źródła *(od 1.2.0)*
Publiczne adresy (np. profile finfluencerów) skanowane przez harmonogram razem z mock-stronami demo.
- `GET /api/v1/watchlist` → `{"items": WatchTarget[], "schedule": "interval: 15 min" | "cron: */30 * * * * (UTC)" | "disabled", "scheduler_next_run": "ISO-8601" | null}`
- `POST /api/v1/watchlist` z `{"url": "https://...", "label": "opcjonalnie", "module_ids": [1,2,3], "use_playwright": false}` → `201 WatchTarget`; `400` dla adresu zablokowanego przez anty-SSRF, `409` gdy URL już jest na liście.
- `PATCH /api/v1/watchlist/{id}` z `{"enabled": true | false}` → `200 WatchTarget`; `404` dla nieistniejącego ID.
- `DELETE /api/v1/watchlist/{id}` → `204`; `404` dla nieistniejącego ID.
- `POST /api/v1/watchlist/run` → `202 {"job_ids": [...], "skipped": [...]}` — natychmiastowe uruchomienie skanu harmonogramu; cele już przetwarzane trafiają do `skipped`.

- *(od 1.3.0)* `POST /api/v1/watchlist/seed` → `200 {"added": 4, "total": 6}` — idempotentne dodanie startowych celów (`data/watchlist_seed.json` + domeny podmiotów z rejestru KNF).
- *(od 1.3.0)* URL-e są kanonikalizowane (mała litera hosta, bez fragmentu, parametrów `utm_*`/`fbclid`/..., domyślnego portu i końcowego `/`), więc `409` obejmuje też inne zapisy tego samego adresu. `POST` przyjmuje opcjonalne `follow_depth` (0–2).

`WatchTarget`: `{"id": 1, "url": "https://...", "label": null, "module_ids": [1,2,3], "use_playwright": false, "follow_depth": 0, "enabled": true, "created_at": "ISO-8601", "last_enqueued_at": "ISO-8601" | null}`

### `GET /api/v1/reports/{module_id}` *(od 1.2.0)*
Raport modułu (`1`–`3`): dane firmy inwestycyjnej, dane podmiotu reklamującego, treść i dokładny URL.
- Query params (opcjonalne): `format` (`json` domyślnie | `csv`), `min_risk_score`, `status`, `date_from`, `date_to`.
- `json`: `{"module_id", "module_name", "generated_at", "knf_snapshot_date", "total", "items": [...]}`.
- `csv`: UTF-8 z BOM, separator `;`, nagłówek `Content-Disposition: attachment`; listy (`evidence_quotes`, `violated_rule_ids`) łączone ` | `; komórki zaczynające się od `=`, `+`, `-`, `@` poprzedzone `'` (ochrona przed CSV injection).
- Kolumny: `id, detected_at, updated_at, risk_score, risk_level, status, entity_name, knf_registry_status, promoter_name, source_platform, source_url, title, content_excerpt, evidence_quotes, violated_rule_ids, analyst_note`.

### Discovery *(od 1.3.0)*
- `POST /api/v1/discovery/run` → `202 {"queries": [...], "hits": 42, "enqueued": ["https://..."], "job_ids": [...], "skipped_seen": 3, "rejected": 5, "error": null}`; `409` gdy `DISCOVERY_ENABLED=false`. Brak odpowiedzi SearXNG daje `error` i pustą listę `enqueued`.
- `GET /api/v1/discovery/recent?limit=50` → `{"enabled": true, "schedule": "cron: 0 */6 * * * (UTC)" | "disabled", "items": [{"url", "query", "engine", "title", "first_seen_at", "last_enqueued_at"}]}`.

### `GET /api/v1/knf-registry` & `GET /api/v1/rules`
- `/api/v1/knf-registry`: lokalny snapshot podmiotów KNF (data, źródła URL z załączników UKNF, lista podmiotów).
- *(od 1.3.0)* `POST /api/v1/knf-registry/refresh?dry_run=false` → `{"snapshot_date", "written_to", "added": {kategoria: [...]}, "removed": {...}, "kept_old": {kategoria: powód}, "errors": {kategoria: błąd}}`. Kategoria, która zwróci mniej niż połowę poprzednich wpisów, zostaje bez zmian.
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
| `1.4.0` | `IncidentDetail.prompt_injection_snippets`, `hidden_text_snippets`, `quote_checks`; `GET /incidents/{id}/similar`, `/versions`, `/evidence-pack`; `StatsResponse.verified_decisions`; `share_mode`, `reporter_display_name`, `reporter_key` w żądaniach analizy; fallback OCR dla zrzutów; `GET /api/v1/intelligence/graph`; reguła `RISK_WARNING_REMOVED`. Bez usuwania istniejących pól i ścieżek. |
| `1.3.0` | Crawler: pola `origin`, `follow_depth`, `follow_max_pages` w `CrawlTriggerRequest`; `origin` w `CrawlJobRecord`; `409` dla duplikatu w kolejce; `follow_depth` w `WatchTarget`; `POST /api/v1/watchlist/seed`; `/api/v1/discovery/*`; `POST /api/v1/knf-registry/refresh`; `DomMetrics.responsive_overflow_viewports`. Bez usuwania istniejących pól i ścieżek. |
| `1.2.0` | Filtr `risk_level` w `GET /api/v1/incidents`; endpointy `/api/v1/watchlist*` i `GET /api/v1/reports/{module_id}`; nowa wartość `source_platform: "x"`. Bez zmian istniejących pól, typów i ścieżek. |
| `1.1.0` | Dodane endpointy `POST /api/v1/analyze/text`, `POST /api/v1/analyze/url`, `PATCH /api/v1/incidents/{incident_id}/label`; nowa wartość `source_platform: "manual"`; `analysis_complete` może zawierać `extra.incident_ids`. Bez zmian istniejących pól, typów i ścieżek. |
| `1.0.0` | Zamrożenie kontraktu: model `Incident`, REST (`/health`, `/incidents`, `/status`, `/stats`, `/crawl/*`, `/knf-registry`, `/rules`), WebSocket `/ws/alerts`. |
