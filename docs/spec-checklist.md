# Checklista zgodności ze specyfikacją UKNF (#InvestWatch)

Źródła: `Opis Wyzwania HackNation UKNF 19.11.pdf` + 4 załączniki DOCX (kryteria ryzyka, tematy 1–3).
Stan na 2026-11-21. Testy backendu: `134 passed`.

## ✅ Zrobione

### Backend i scraping
- [x] Crawler na httpx, opcjonalny Playwright (strony w JS), ochrona anty-SSRF, limity (timeout, rozmiar, przekierowania)
- [x] Rotacja User-Agent i proxy przy każdym żądaniu (`CRAWLER_PROXIES`)
- [x] Parsery social mediów: Facebook, Instagram, TikTok, YouTube, X (OpenGraph, JSON-LD)
- [x] Wynik z HTML zapisywany jako JSON, w bazie SQLite (metadane) i w lokalnym object store (`OBJECT_STORE_DIR`)
- [x] Harmonogram APScheduler (interwał albo crontab w `CRAWLER_CRON`) i watchlista do okresowego skanowania
- [x] Kolejka zadań (`CrawlQueueWorker`, trwała w SQLite)

### AI
- [x] Preprocessing: czyszczenie HTML, normalizacja, tokeny, embeddingi (lokalne 128-dim lub z Ollamy), deduplikacja
- [x] Ollama z Gemmą, odpowiedzi w ustalonym formacie JSON, scoring 0–1, tryb zapasowy na regułach (`demo_fallback`), gdy Ollama nie działa
- [x] Agregator łączy wyniki modułów 1–3 w jeden obiekt
- [x] Moduł 1: finfluencerzy, `promoter_name`, URL, raport CSV/JSON
- [x] Moduł 2: wszystkie reguły 1–18 (z 12a/12b) w `data/risk_criteria_rules.json`, analiza wyglądu strony (czcionka, kontrast WCAG, `<details>`, przepełnienie na mobile)
- [x] Moduł 3: shadow advisory, porównanie z rejestrem KNF, wykrywanie podszywania się pod firmy z rejestru, Lista Ostrzeżeń
- [x] Dodatki: wykrywanie prompt injection, odrzucanie cytatów nieobecnych w treści, RAG z przykładami few-shot, analiza zrzutów ekranu (VLM), benchmark P/R/F1

### Frontend
- [x] React 19 + Tailwind + shadcn/Radix, komponenty oparte na propsach
- [x] Wykres trendu (Recharts), WebSocket z alertami na żywo, zmiana statusu rekordu
- [x] Panel kalibracji: próg zmienia TP/FP/FN, precyzję i pełność
- [x] Brak `console.log` w `frontend/src/` (jedyne wywołania są w pluginie health-check, który działa tylko na serwerze deweloperskim)

### Wymagania techniczne
- [x] Cały stos startuje jedną komendą `docker compose up`, Ollama w opcjonalnym profilu `ai`
- [x] Tylko open source, zero płatnych API, sekrety wyłącznie w `.env`
- [x] Audyt zależności (`pip-audit`, `yarn audit`, rezolucje), opis w `docs/security-licenses.md`
- [x] README z Quick Startem, wymaganiami sprzętowymi i tabelą konfiguracji
- [x] Opis procesu pracy z asystentami AI (`docs/ai-workflow.md`), pod kryterium 20% za proces wytwarzania

## ❌ Do dodania lub poprawienia

### Wymagania formalne (blokują oddanie projektu)
- [ ] **Prezentacja w PDF**: w repo jej nie ma
- [ ] **Szczegółowy opis i tytuł projektu** do formularza zgłoszenia
- [ ] (opcjonalnie) **Film do 3 minut**

### Automatyczny crawling internetu
Stan obecny: cron (`scheduled_scan` w `backend/app/queue_worker.py`) co 15 minut skanuje ponownie tylko mocki demo i URL-e z watchlisty. Jest to cykliczny rescan, a nie monitoring sieci.
- [ ] **Odkrywanie nowych treści**: lokalny SearXNG w Docker Compose, który cron odpytuje frazami typu „<nazwa firmy z rejestru KNF> + kod polecający / reklama / CFD”. Nowe URL-e trafiają automatycznie do kolejki, z deduplikacją i ochroną anty-SSRF.
- [ ] **Seed watchlisty**: publiczne strony brokerów z rejestru KNF i publiczne profile (teraz watchlista startuje pusta)
- [ ] (opcjonalnie) Chodzenie po linkach w obrębie domeny, z ograniczeniem głębokości (teraz każdy cel to jedna strona)

### Dashboard (spec, pkt 3)
- [ ] **Filtry po dacie, źródle (platformie) i poziomie ryzyka.** Teraz jest tylko filtr po module (`frontend/src/pages/Dashboard.jsx`). Backend już obsługuje `date_from/date_to`, `source_platform` i `risk_level`.
- [ ] **Uruchamianie crawla z panelu** (`POST /api/v1/crawl/trigger`) i lista zadań (`GET /api/v1/crawl/jobs`)
- [ ] **Widok watchlisty** (dodawanie i usuwanie źródeł, „uruchom teraz”). Endpointy istnieją, UI nie ma.
- [ ] **Pobieranie raportów modułów z backendu** (`/api/v1/reports/{1|2|3}?format=csv`). Teraz eksport jest liczony lokalnie z listy w przeglądarce.
- [ ] Nieaktualny komentarz w `frontend/src/lib/api.js` (mówi o v1.1.0, kontrakt jest w 1.2.0)
- [ ] Dodac pobieranie tekstu ze zrzutu ekranu, dla zgloszenia obywatelskiego

### Zgodność ze specem
- [ ] **Reguła 8 wymaga też tabletu.** Spec wymienia desktop, tablet i telefon, a `backend/app/scraper/browser.py` sprawdza tylko 1280 i 375 px. Brakuje widoku ~768×1024.
- [ ] **Odświeżanie rejestru KNF** z 5 URL-i podanych w załącznikach do tematów 1 i 2 (skrypt lub job aktualizujący `data/knf_registry_snapshot.json`), a w UI data snapshotu
- [ ] (warto rozważyć) Kolejka na zewnętrznym narzędziu (Redis z RQ/Celery/Arq) i MinIO jako object storage, pod kryterium architektury i skalowalności
- [ ] (warto rozważyć) Skan **Snyk** wprost wymieniony w specu: `snyk test` z wynikiem w `docs/security-licenses.md` albo workflow w GitHub Actions (w repo nie ma `.github/`)

### Przed oceną Jury
- [ ] Przejść cały scenariusz demo na `docker compose up` z Ollamą: crawl, alert na WebSockecie, zmiana statusu, kalibracja
- [ ] Sprawdzić konsolę przeglądarki na buildzie produkcyjnym (Jury patrzy na `Console.log`)
- [ ] Wpisać aktualny wynik `python -m scripts.evaluate_detection --mode both` do prezentacji jako dowód trafności klasyfikacji
