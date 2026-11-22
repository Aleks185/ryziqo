# Checklista zgodności ze specyfikacją UKNF (Ryziqo)

Źródła: `Opis Wyzwania HackNation UKNF 19.11.pdf` + 4 załączniki DOCX (kryteria ryzyka, tematy 1–3).
Stan na 2026-11-21 (wieczór). Testy backendu: `194 passed`. Benchmark fallback (53 przypadki): P 0,960 / R 0,686 / F1 0,800. Stos Docker w wersji API 1.3.0 uruchomiony i sprawdzony (backend, frontend, SearXNG).

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
- [x] Anty-SSRF z przypięciem IP (`pinned_request`, ochrona przed DNS rebinding) dla stron, `robots.txt` i list KNF
- [x] Kolejka analiz z formularza (`POST /api/v1/analyze/jobs`, postęp przez SSE, limit 1+8 i HTTP 429), cache ETag/304 dla pobrań URL (`backend/app/analysis_queue.py`)
- [x] Rejestr KNF z knf.gov.pl: 758 podmiotów (banki i domy maklerskie, oddziały, notyfikowane firmy zagraniczne) + 4 [DEMO]; synchronizacja z paginacją i bezpiecznikami (`backend/app/knf_sync.py`, `KNF_SYNC_USER_AGENT`)

### AI
- [x] Preprocessing: czyszczenie HTML, normalizacja, tokeny, embeddingi (lokalne 128-dim lub z Ollamy), deduplikacja
- [x] Ollama z Gemmą, odpowiedzi w ustalonym formacie JSON, scoring 0–1, tryb zapasowy na regułach (`demo_fallback`), gdy Ollama nie działa
- [x] Agregator łączy wyniki modułów 1–3 w jeden obiekt
- [x] Moduł 1: finfluencerzy, `promoter_name`, URL, raport CSV/JSON
- [x] Moduł 2: wszystkie reguły 1–18 (z 12a/12b) w `data/risk_criteria_rules.json`, analiza wyglądu strony (czcionka, kontrast WCAG, `<details>`, przepełnienie na mobile)
- [x] Moduł 3: shadow advisory, porównanie z rejestrem KNF, wykrywanie podszywania się pod firmy z rejestru, Lista Ostrzeżeń
- [x] Dodatki: wykrywanie prompt injection, odrzucanie cytatów nieobecnych w treści, RAG z przykładami few-shot, analiza zrzutów ekranu (VLM), benchmark P/R/F1
- [x] Fałszywe alarmy na prawdziwych stronach brokerów (sprawdzone crawlem xtb.com, bossa.pl, etoro.com; po poprawkach wszystkie poniżej progów):
  - reguły 6 i 7 tylko wtedy, gdy ostrzeżenie jest **wyłącznie** w stopce lub za kliknięciem (legalne strony powtarzają je w stopce)
  - moduł 1 pomija kody polecające na oficjalnej domenie firmy z rejestru (to komunikacja własna, zakres modułu 2)
  - podszywanie: subdomeny oficjalnych domen są zaufane (`online.bossa.pl`), fuzzy matching tylko dla marek z ręcznymi aliasami, słowa ogólne nie są literówką marki (`bank.pl` ≠ mBank); 0 fałszywych alarmów na 40 popularnych domenach, podróbki dalej wykrywane

### Frontend
- [x] React 19 + Tailwind + shadcn/Radix, komponenty oparte na propsach
- [x] Wykres trendu (Recharts), WebSocket z alertami na żywo, zmiana statusu rekordu
- [x] Panel kalibracji: próg zmienia TP/FP/FN, precyzję i pełność
- [x] Brak `console.log` w `frontend/src/` (jedyne wywołania są w pluginie health-check, który działa tylko na serwerze deweloperskim)
- [x] Build produkcyjny (`CI=true yarn build`) bez ostrzeżeń; data snapshotu rejestru KNF na dashboardzie
- [x] Zgłoszenie obywatelskie i analiza ze zrzutu ekranu (PNG/JPG/WebP do 10 MB, odczyt przez model wizyjny; wymaga Ollamy z modelem multimodalnym)

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
- [x] Timeout liczony per żądanie (czekanie z grzeczności poza budżetem), wolna podstrona nie wywraca zadania, błędy pobierania z nazwą hosta zamiast przypiętego IP (`fetcher.py`, `queue_worker.py`)
- [x] Discovery sprawdzone na żywo (2026-11-21): SearXNG `2026.11.21-c6ee3e9fd` (tag przypięty), 3 frazy → 30 wyników → 6 nowych URL-i w kolejce → 6 przeanalizowanych; strony afiliacyjne wykryte (M1), oficjalne strony brokera bez fałszywych alarmów
- [x] Seed watchlisty sprawdzony: xtb.com i bossa.pl odpowiadają i pozwalają w `robots.txt`; po starcie Dockera watchlista ma 9 celów (4 z seeda + domeny z rejestru: mbank.pl, pkobp.pl, santander.pl, interactivebrokers.com/.ie)
- [ ] etoro.com i trading212.com odpowiadają `403` na nagłówek bota (ochrona antybotowa). Zdecydować: usunąć z seeda, skanować przez Playwright albo zostawić jako znane ograniczenie
- [ ] Włączyć discovery w Dockerze: `.env` z `DISCOVERY_ENABLED=true` i `docker compose --profile discovery up -d` (domyślnie wyłączone)
- [ ] (warto rozważyć) Publiczne profile social mediów w seedzie (teraz tylko strony brokerów)

### Dashboard (spec, pkt 3)
- [ ] **Filtry po dacie, źródle (platformie) i poziomie ryzyka.** Teraz jest tylko filtr po module (`frontend/src/pages/Dashboard.jsx`). Backend już obsługuje `date_from/date_to`, `source_platform` i `risk_level`.
- [x] **Uruchamianie crawla z panelu** (`POST /api/v1/crawl/trigger`) i lista zadań (`GET /api/v1/crawl/jobs`) — strona „Crawler” (`/crawler`, `frontend/src/pages/Crawler.jsx`)
- [x] **Widok watchlisty** (dodawanie, włączanie/wyłączanie i usuwanie źródeł, „skanuj teraz”, źródła startowe, wynik ostatniego skanu) na stronie „Crawler”
- [ ] **Pobieranie raportów modułów z backendu** (`/api/v1/reports/{1|2|3}?format=csv`). Teraz eksport jest liczony lokalnie z listy w przeglądarce.
- [x] Komentarz w `frontend/src/lib/api.js` zaktualizowany (CONTRACT.md v1.3.0)
- [x] Pobieranie tekstu ze zrzutu ekranu dla zgłoszenia obywatelskiego (VLM, patrz sekcja Frontend)
- [x] Widok wyników discovery (`GET /api/v1/discovery/recent`) i przycisk „uruchom discovery” w panelu (strona „Crawler”)

### Zgodność ze specem
- [x] **Reguła 8: desktop, tablet i telefon** (1280, 768 i 375 px w `backend/app/scraper/browser.py`; evidence podaje widok)
- [x] **Odświeżanie rejestru KNF** (`python -m scripts.refresh_knf_registry`, `POST /api/v1/knf-registry/refresh`, `KNF_REFRESH_CRON`), data snapshotu na dashboardzie
- [x] **Parser list KNF sprawdzony na prawdziwych stronach (2026-11-21).** knf.gov.pl zrywa połączenia z nagłówkiem bota (robots.txt pozwala wszystkim), więc synchronizacja przedstawia się jako przeglądarka (`KNF_SYNC_USER_AGENT`). Parser czyta tabele klucz–wartość („Nazwa podmiotu”), pomija dawne nazwy (`<strike>`), przechodzi paginację `?page=N`: 754 podmioty (10 banków, 27 DM, 10 oddziałów, 707 transgranicznych). Wpisy z ręcznymi aliasami nie są usuwane automatycznie (`unmatched_kept` w raporcie), a fuzzy-matching podszywania działa tylko na markach z aliasami.
- [x] Snapshot rejestru w repo zastąpiony danymi z knf.gov.pl (2026-11-21, 758 podmiotów + 4 [DEMO]); ręczne wpisy scalone z oficjalnymi nazwami KNF (BOŚ, PKO BP, mBank, Santander→Erste, OANDA TMS, IBKR), dawne nazwy zostały aliasami.
- [ ] Do potwierdzenia ręcznie: eToro (Europe) Ltd. i Saxo Bank A/S nie występują na pobranych listach notyfikacji; Trading 212 figuruje jako „Trading 212 Ltd” i „Trading 212 EU GmbH”, a w snapshocie jest „Trading 212 Markets Ltd.” — wpisy ręczne zostawione bez zmian
- [ ] Lista dopisków podszywania nie łapie części wzorców (`pkobp-makler.com`, `saxobank-pro.pl`, `trading-212-bonus.pl`) — rozważyć rozszerzenie `SUSPICIOUS_AFFIXES` (makler, pro, bonus)
- [ ] (warto rozważyć) Kolejka na zewnętrznym narzędziu (Redis z RQ/Celery/Arq) i MinIO jako object storage, pod kryterium architektury i skalowalności
- [ ] (warto rozważyć) Skan **Snyk** wprost wymieniony w specu: `snyk test` z wynikiem w `docs/security-licenses.md` albo workflow w GitHub Actions (w repo nie ma `.github/`)

### Wyróżniki ponad specyfikację (priorytet wg ROI)
Uporządkowane od najwyższego stosunku efektu na demo / wartości dla UKNF do nakładu pracy:

- [x] **P1 — Mechanizmy AI widoczne w UI** (karta incydentu `IncidentDetail.jsx`):
  - **Prompt injection**: baner „Wykryto próbę manipulacji audytem AI” z wykrytymi poleceniami i ukrytym tekstem (`prompt_injection_snippets`, `hidden_text_snippets` w `IncidentDetail`); mock `data/mock_sites/broker_promo_prompt_injection.html` (biały tekst, `font-size:0`), dopisany do seeda demo i golden datasetu.
  - **RAG / klony i Human-in-the-Loop**: panel „Podobne wcześniejsze decyzje / możliwe klony” (`GET /incidents/{id}/similar`, oznaczenie KLON) oraz licznik „Decyzje analityków użyte przez RAG” w `Calibration.jsx` (`verified_decisions` w `/stats`).
  - **Anti-Hallucination**: przy każdym cytacie oznaczenie „zweryfikowany dosłownie / ≈ / sygnał systemu” (`quote_checks` z `verify_quote_in_document`).
- [x] **P2 — Zgłoszenie obywatelskie ze zrzutu ekranu → alert na żywo** (`Citizen.jsx`): odczyt przez VLM (z wykrywaniem logo KNF/NBP, reguła 17), a bez modelu wizyjnego lokalny OCR RapidOCR (`backend/app/ocr.py`, build-arg `INSTALL_OCR`). Obywatel wybiera: tylko werdykt (nic nie jest zapisywane), przekazanie anonimowe (bez IP/UA) albo podpisane pseudonimem z losowym kluczem przeglądarki (HMAC), co przygotowuje dane pod ranking prawdziwych zgłoszeń. PESEL i numery kart są maskowane. Przekazane zgłoszenia wysokiego ryzyka idą do analityka przez WebSocket (`high_risk_alert`).
  - [ ] Ranking zgłaszających (dane już są: `reporter_display_name`, `reporter_key_hash` w `threat_reports`)
  - [ ] Sprawdzić jakość OCR dla polskich znaków na prawdziwych zrzutach (model PP-OCRv4 ch/en może gubić diakrytyki)
- [ ] **P3 (Wysokie ROI) — Generator projektu pisma nadzorczego / notatki pod Listę Ostrzeżeń** — 1 klik z karty incydentu (DOCX/MD) bazujący na istniejących `violated_rules`, `legal_basis`, zweryfikowanych cytatach i statusie w rejestrze KNF: szkic wezwania do wyjaśnień (Moduł 1/2) albo notatki pod wpis na Listę Ostrzeżeń / art. 178 u.o.i.f. (Moduł 3).
- [x] **P4 — Paczka dowodowa „Chain of Custody” i „Znikające ostrzeżenie”**: przycisk w karcie incydentu pobiera `evidence_pack_<id>.zip` (`GET /incidents/{id}/evidence-pack`: HTML, JSON ekstrakcji, zrzuty, incydent, zgłoszenie z przekierowaniami/IP, historia wersji, `manifest.json` z SHA-256 i `manifest.sha256`; opcjonalnie znacznik RFC 3161 przez `EVIDENCE_TSA_URL`). Panel „Historia wersji strony” (`GET /incidents/{id}/versions`) z diffem zdań; przy usunięciu ostrzeżenia lub zmniejszeniu jego czcionki o ≥ 25% między skanami reguła `RISK_WARNING_REMOVED` (wynik ≥ 0,75, alert WS).
  - [ ] Sprawdzić RFC 3161 na prawdziwym TSA (np. `https://freetsa.org/tsr`) i weryfikację `openssl ts -verify`
- [ ] **P5 (Średnio-wysokie ROI) — Wizualny „X-Ray” naruszeń na zrzutach ekranu (Desktop / Tablet / Mobile)** (łączy się z Regułą 8 w sekcji wyżej) — nakładanie przez Playwright ramek (bounding boxes) na obietnicę zysku vs ukrytą klauzulę ryzyka (z metrykami fontu i kontrastu) i zestawienie 3 widoków (`1280`, `768`, `375 px`) obok siebie w `IncidentDetail.jsx`.
- [x] **P6 — Graf powiązań kampanii i sieci finfluencerów**: strona „Mapa powiązań” (`/graph`, `d3-force` + SVG: zoom, przeciąganie, podświetlanie sąsiadów, klik otwiera kartę incydentu lub kampanię). Dane z `GET /api/v1/intelligence/graph`: promotorzy, podmioty z rejestru, domeny docelowe linków (także rozwinięte skróty), kody polecające z parametrów linków, kampanie z bazy zgłoszeń, Lista Ostrzeżeń i krawędzie klonów. W trybie DEMO graf z lokalnych incydentów.
- [ ] **P7 (Niższe ROI / bardziej złożone, ale spektakularne na demo) — Analiza krótkiego wideo i audio z TikToka / Reels** — lokalny `faster-whisper` (transkrypcja mowy z reklam „link w bio”) + wybrane klatki (np. migająca plansza końcowa z drobnym druczkiem) przekazane do VLM (`vision_analyzer.py`) i dalej do standardowego pipeline'u Modułów 1–3.

### Przed oceną Jury
- [x] Scenariusz demo przez API w trybie bez Ollamy: crawl mocków (14 stron), 8 alertów `high_risk_alert` na WebSockecie, zmiana statusu i etykiety, raporty modułów 1–3, kalibracja (P 1,00 / R 0,91 / F1 0,95)
- [ ] Ten sam scenariusz **z Ollamą** (`--profile ai` albo Ollama na hoście) i przeklikany w przeglądarce
- [ ] Sprawdzić konsolę przeglądarki na buildzie produkcyjnym (Jury patrzy na `Console.log`). Jedyny `console.log` w bundlu pochodzi z domyślnej strony błędu react-routera i pojawia się tylko przy wywrotce aplikacji — można dodać własny `errorElement`
- [ ] Wpisać aktualny wynik `python -m scripts.evaluate_detection --mode both` do prezentacji jako dowód trafności klasyfikacji
