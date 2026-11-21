# Checklista zgodności ze specyfikacją UKNF (#InvestWatch)

Źródła: `Opis Wyzwania HackNation UKNF 19.11.pdf` + 4 załączniki DOCX (kryteria ryzyka, tematy 1–3).
Stan na 2026-11-21. Testy backendu: `160 passed`.

## ✅ Zrobione

### Backend i scraping
- [x] Crawler na httpx, opcjonalny Playwright (strony w JS), ochrona anty-SSRF, limity (timeout, rozmiar, przekierowania)
- [x] Rotacja User-Agent i proxy przy każdym żądaniu (`CRAWLER_PROXIES`)
- [x] Parsery social mediów: Facebook, Instagram, TikTok, YouTube, X (OpenGraph, JSON-LD)
- [x] Wynik z HTML zapisywany jako JSON, w bazie SQLite (metadane) i w lokalnym object store (`OBJECT_STORE_DIR`)
- [x] Harmonogram APScheduler (interwał albo crontab w `CRAWLER_CRON`) i watchlista do okresowego skanowania
- [x] Kolejka zadań (`CrawlQueueWorker`, trwała w SQLite)
- [x] Odkrywanie nowych treści: SearXNG w profilu `discovery`, zapytania z rejestru KNF (`data/discovery_queries.json`, rotacja), deduplikacja, denylist, anty-SSRF (`backend/app/discovery.py`)
- [x] Seed watchlisty (`data/watchlist_seed.json` + domeny z rejestru KNF, `POST /api/v1/watchlist/seed`)
- [x] Chodzenie po linkach w obrębie domeny (`follow_depth` 0–2, `follow_max_pages`, priorytet regulaminów i stron o ryzyku)
- [x] Kanonikalizacja URL (watchlista, kolejka, discovery), `409` dla duplikatu w kolejce
- [x] `robots.txt` + `Crawl-delay` + odstęp per host (`backend/app/scraper/politeness.py`)

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
- [x] Discovery sprawdzone na żywo (2026-11-21): SearXNG `2026.11.21-c6ee3e9fd` (tag przypięty), 3 frazy → 30 wyników → 6 nowych URL-i w kolejce → 6 przeanalizowanych; strony afiliacyjne wykryte (M1), oficjalne strony brokera bez fałszywych alarmów
- [ ] Zweryfikować URL-e w `data/watchlist_seed.json` (czy strony odpowiadają i nie blokują w `robots.txt`)
- [ ] (warto rozważyć) Publiczne profile social mediów w seedzie (teraz tylko strony brokerów)

### Dashboard (spec, pkt 3)
- [ ] **Filtry po dacie, źródle (platformie) i poziomie ryzyka.** Teraz jest tylko filtr po module (`frontend/src/pages/Dashboard.jsx`). Backend już obsługuje `date_from/date_to`, `source_platform` i `risk_level`.
- [ ] **Uruchamianie crawla z panelu** (`POST /api/v1/crawl/trigger`) i lista zadań (`GET /api/v1/crawl/jobs`)
- [ ] **Widok watchlisty** (dodawanie i usuwanie źródeł, „uruchom teraz”). Endpointy istnieją, UI nie ma.
- [ ] **Pobieranie raportów modułów z backendu** (`/api/v1/reports/{1|2|3}?format=csv`). Teraz eksport jest liczony lokalnie z listy w przeglądarce.
- [ ] Nieaktualny komentarz w `frontend/src/lib/api.js` (mówi o v1.1.0, kontrakt jest w 1.2.0)
- [ ] Dodac pobieranie tekstu ze zrzutu ekranu, dla zgloszenia obywatelskiego

### Zgodność ze specem
- [x] **Reguła 8: desktop, tablet i telefon** (1280, 768 i 375 px w `backend/app/scraper/browser.py`; evidence podaje widok)
- [x] **Odświeżanie rejestru KNF** (`python -m scripts.refresh_knf_registry`, `POST /api/v1/knf-registry/refresh`, `KNF_REFRESH_CRON`), data snapshotu na dashboardzie
- [ ] **Parser list KNF sprawdzić na prawdziwych stronach.** knf.gov.pl zrywał połączenie (ECONNRESET) przy tworzeniu parsera, więc jest generyczny (tabela / CSV / XLSX / lista) i testowany tylko na fixture'ach. Uruchomić `--dry-run` z sieci, która ma dostęp.
- [ ] (warto rozważyć) Kolejka na zewnętrznym narzędziu (Redis z RQ/Celery/Arq) i MinIO jako object storage, pod kryterium architektury i skalowalności
- [ ] (warto rozważyć) Skan **Snyk** wprost wymieniony w specu: `snyk test` z wynikiem w `docs/security-licenses.md` albo workflow w GitHub Actions (w repo nie ma `.github/`)

### Wyróżniki ponad specyfikację (priorytet wg ROI)
Uporządkowane od najwyższego stosunku efektu na demo / wartości dla UKNF do nakładu pracy:

- [ ] **P1 (Najwyższe ROI) — Odsłonięcie gotowych mechanizmów AI w UI** — backend już je posiada, ale nie są widoczne dla Jury:
  - **Prompt Injection**: badge w `frontend/src/pages/IncidentDetail.jsx` („Wykryto próbę manipulacji audytem AI”) + dedykowany mock w `data/mock_sites/` z ukrytym białym tekstem próbującym oszukać model.
  - **RAG / klony kampanii i Human-in-the-Loop**: sekcja „Podobne wcześniejsze decyzje / możliwe klony” w karcie incydentu oraz licznik zweryfikowanych decyzji analityków korygujących prompty w `frontend/src/pages/Calibration.jsx`.
  - **Anti-Hallucination**: oznaczenie przy cytatach, że zostały dosłownie zweryfikowane w treści źródłowej.
- [ ] **P2 (Bardzo wysokie ROI) — Zgłoszenie obywatelskie ze zrzutu ekranu (OCR/VLM) → alert na żywo** (rozszerza punkt z sekcji Dashboard dla `frontend/src/pages/Citizen.jsx`): lokalny OCR (`rapidocr-onnxruntime` lub VLM w Ollama) wyciąga tekst i wykrywa wizualne podszywanie się (np. fałszywe logo KNF/NBP, drobny druk), zwraca prosty werdykt obywatelowi, a po zaznaczeniu zgody wysyła zanonimizowany incydent na żywo przez WebSocket do kolejki analityka.
- [ ] **P3 (Wysokie ROI) — Generator projektu pisma nadzorczego / notatki pod Listę Ostrzeżeń** — 1 klik z karty incydentu (DOCX/MD) bazujący na istniejących `violated_rules`, `legal_basis`, zweryfikowanych cytatach i statusie w rejestrze KNF: szkic wezwania do wyjaśnień (Moduł 1/2) albo notatki pod wpis na Listę Ostrzeżeń / art. 178 u.o.i.f. (Moduł 3).
- [ ] **P4 (Wysokie ROI) — Paczka dowodowa „Chain of Custody” (ZIP + SHA-256) i diff wersji („Znikające ostrzeżenie”)** — eksport `evidence_pack_<id>.zip` z `OBJECT_STORE_DIR` (surowy HTML, zrzuty ekranu, JSON ekstrakcji, nagłówki/przekierowania + manifest `SHA-256`, opcjonalnie znacznik czasu RFC 3161) oraz porównywanie kolejnych snapshotów tego samego URL z alertem przy usunięciu lub zmniejszeniu klauzuli ryzyka.
- [ ] **P5 (Średnio-wysokie ROI) — Wizualny „X-Ray” naruszeń na zrzutach ekranu (Desktop / Tablet / Mobile)** (łączy się z Regułą 8 w sekcji wyżej) — nakładanie przez Playwright ramek (bounding boxes) na obietnicę zysku vs ukrytą klauzulę ryzyka (z metrykami fontu i kontrastu) i zestawienie 3 widoków (`1280`, `768`, `375 px`) obok siebie w `IncidentDetail.jsx`.
- [ ] **P6 (Średnie ROI / mocny efekt „wow”) — Graf powiązań kampanii i sieci finfluencerów** — interaktywny graf łączący `promoter_name`, rozwinięte skrócone linki / kody polecające (`CRAWLER_EXPAND_SHORT_LINKS`), domeny-klony (embeddingi) oraz docelowy podmiot KNF / Listę Ostrzeżeń w mapę sieci dystrybucji.
- [ ] **P7 (Niższe ROI / bardziej złożone, ale spektakularne na demo) — Analiza krótkiego wideo i audio z TikToka / Reels** — lokalny `faster-whisper` (transkrypcja mowy z reklam „link w bio”) + wybrane klatki (np. migająca plansza końcowa z drobnym druczkiem) przekazane do VLM (`vision_analyzer.py`) i dalej do standardowego pipeline'u Modułów 1–3.

### Przed oceną Jury
- [ ] Przejść cały scenariusz demo na `docker compose up` z Ollamą: crawl, alert na WebSockecie, zmiana statusu, kalibracja
- [ ] Sprawdzić konsolę przeglądarki na buildzie produkcyjnym (Jury patrzy na `Console.log`)
- [ ] Wpisać aktualny wynik `python -m scripts.evaluate_detection --mode both` do prezentacji jako dowód trafności klasyfikacji
