# Ryziqo — raport wdrożenia, 21 listopada 2026

## Środowisko i konfiguracja

FastAPI działa w pojedynczym procesie Uvicorn w Docker Compose. SQLite przechowuje rejestr i cache. React łączy się z API przez Nginx. Testy odbiorcze używały tych samych obrazów aplikacji, odrębnej bazy i rzeczywistej Ollamy na hoście Windows.

Ollama 0.40.16 używa modelu Gemma 3 4B (tag `gemma3:4b`, identyfikator `68ceab7e468a`, kwantyzacja Q4_K_M). API modelu potwierdziło obsługę generowania tekstu i wizji. Zainstalowany wcześniej `nomic-embed-text` dostarcza wektory. Sprzęt to Intel Core i5-13450HX (10 rdzeni fizycznych, 16 wątków), około 15,7 GiB RAM i NVIDIA RTX 3050 Laptop z 6 GiB VRAM.

Ustawienia procesu Ollamy w Windows i opcjonalnego profilu Compose to `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1` i `OLLAMA_MAX_QUEUE=8`, a także `OLLAMA_FLASH_ATTENTION=1` i `OLLAMA_KV_CACHE_TYPE=q8_0`. Generowanie używa kontekstu 2048, limitu odpowiedzi 300, temperatury 0.1, 10 wątków CPU i `keep_alive=60m`. Klient serializuje wywołania modelu, w tym embeddingi, i wyładowuje poprzedni model przy zmianie. Serwer Ollamy nasłuchuje lokalnie.

## Wyniki odbioru

- **139 testów backendu przeszło.** Starlette zgłosił jedno ostrzeżenie o wycofywanym użyciu httpx w kliencie testowym.
- Test wysłał dwa teksty i publiczny adres example.org równocześnie. Serwer ukończył je w kolejności zgłoszenia. Test przepełnienia potwierdził limit 1+8, HTTP 429 i anulowanie zadania oczekującego.
- Dostęp do publicznej strony sprawdzono z prawdziwym pobraniem przez HTTPS. Testy integracyjne zasymulowały odpowiedź 403 i timeout. Błędy pobierania nie tworzą werdyktu. Działające API odrzuciło localhost z HTTP 400. Testy sprawdziły blokady również przy przekierowaniach i pobieraniu zasobów przeglądarki.
- Silny ETag pozwala ponownie potwierdzić treść. Kopia pobrania jest przechowywana do 15 minut, najwyżej dla czterech reprezentacji. Raport URL ma osobny TTL 15 minut i zależy od hasha treści. Test obejmuje warunkowy GET i odpowiedź 304. Raporty pozostałych źródeł mają TTL 24 godziny.
- Chromium przesłał zrzut jako plik, przez przeciągnięcie i zdarzenie schowka. Model odczytał ostrzeżenie „Istnieje ryzyko utraty kapitału” zapisane fontem 15 px obok nagłówka 32 px. Osobno sprawdzono rzeczywisty skrót Ctrl+V i lokalny podgląd przed wysłaniem. Obsługa schowka opiera się na przeglądarkowym zdarzeniu paste. Nie przeprowadzono testu klawiatury na macOS.
- Formularz przetestowano przy 1440 i 390 px. Szerokość formularza we wszystkich trzech trybach wyniosła odpowiednio 952 i 358 px. Szerokość dokumentu odpowiadała obszarowi przeglądarki. Konsola i obsługa błędów JavaScript nie zgłosiły problemów w teście przełączania. Weryfikacja dotyczyła układu, zastosowanych klas i zachowania, bez porównania piksel po pikselu.
- Zdarzenia SSE dostarczają stan, fragmenty generowanej odpowiedzi i gotowy raport. Test obejmuje wznowienie z Last-Event-ID. Cache kolejnych identycznych zgłoszeń pomija wywołanie modelu. Analiza regułowa pozostaje dostępna dla tekstu w trybie DEMO.

## Czasy i pamięć

Wartości w sekundach pochodzą z logów izolowanej instancji. Czas całkowity i TTFT biegną od przyjęcia zgłoszenia, więc obejmują oczekiwanie. Czas ładowania pochodzi z odpowiedzi generatywnych Ollamy. RSS backendu podaje najwyższą dotychczasową wartość dla tego procesu.

| Próba | Kolejka | Preprocessing | Ładowanie | Pierwszy token | Razem | Cache | RSS backendu (MiB) |
|---|---:|---:|---:|---:|---:|---|---:|
| Tekst o ryzyku ETF | 0.000 | 0.001 | 6.52 | 9.98 | 20.026 | nie | 65.9 |
| Obietnica zysku | 20.019 | 0.001 | 6.51 | 29.04 | 39.981 | nie | 66.1 |
| Publiczny URL | 39.971 | 0.001 | 6.48 | 49.11 | 53.108 | nie | 67.8 |
| Powtórzony tekst | 0.000 | 0.000 | 0.00 | — | 0.067 | tak | 68.1 |
| Zrzut z pliku | 0.000 | 0.716 | 6.87 | 3.28 | 40.553 | nie | 74.5 |
| Ten sam zrzut, przeciągnięcie | 0.000 | 0.000 | 0.00 | — | 0.035 | tak | 75.8 |
| Ten sam zrzut, schowek | 0.000 | 0.000 | 0.00 | — | 0.026 | tak | 77.2 |

W trakcie próbkowania Windows co 3 s zanotowano do 1345 MiB pamięci roboczej procesu modelu i do 269 MiB dla usługi Ollamy. Są to odrębne maksima. API Ollamy raportowało do 2749 MiB VRAM modelu. Po wygaśnięciu minuty bezczynności lista załadowanych modeli była pusta, a usługa zajmowała około 56 MiB RAM. Pomiar dotyczy tej maszyny i przykładów odbiorczych.

## Przykładowe oceny

- text — 50/100. Model zapisany przy incydencie: gemma3:4b + uknf-18rules.
- text — 74/100. Model zapisany przy incydencie: gemma3:4b + uknf-18rules.
- url — 12/100. Model zapisany przy incydencie: gemma3:4b + uknf-18rules.
- screenshot — 34/100. Model zapisany przy incydencie: gemma3:4b + uknf-18rules.

Wynik w raporcie ma skalę 0–100, a wynik incydentu nadal ma skalę 0–1. Przykłady sprawdzają działanie ścieżek analizy. Trafność klasyfikacji wymaga oceny na oznaczonym zbiorze reklam.

## Pliki wdrożenia

- `.env.example`
- `CONTRACT.md`
- `backend/app/ai/context.py`
- `backend/app/ai/ollama_client.py`
- `backend/app/ai/preprocessor.py`
- `backend/app/ai/prompting.py`
- `backend/app/ai/vision_analyzer.py`
- `backend/app/analysis_queue.py`
- `backend/app/config.py`
- `backend/app/database.py`
- `backend/app/image_processor.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/queue_worker.py`
- `backend/app/routers/analyze.py`
- `backend/app/scraper/browser.py`
- `backend/app/scraper/fetcher.py`
- `backend/app/scraper/ssrf.py`
- `backend/tests/test_ai_detection.py`
- `backend/tests/test_analysis_workflow.py`
- `docker-compose.yml`
- `docs/ollama-llm-setup.md`
- `docs/raport-wdrozenia-analizy.md`
- `frontend/nginx.conf`
- `frontend/src/lib/api.js`
- `frontend/src/lib/i18n.js`
- `frontend/src/lib/store.js`
- `frontend/src/pages/Analyze.jsx`
- `frontend/src/pages/Citizen.jsx`

## Biblioteki i licencje

Nie dodano pakietów Python ani JavaScript. Przetwarzanie obrazu korzysta z już zainstalowanego Playwright i Chromium. Kolejka, SHA-256 i trwały cache wykorzystują istniejący runtime Pythona i SQLite, a klient zdarzeń korzysta z przeglądarkowego EventSource.
