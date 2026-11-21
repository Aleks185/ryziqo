# INVESTWATCH — plan pracy Krzysztofa
**HackNation 2026 | 21–22 listopada 2026**  
**Rola:** Backend, scraping, 3 moduły AI, SQLite, komunikacja WebSocket, Docker Compose, audyt Python, README i weryfikacja startu.

## 1. Odpowiedzialność i zasady współpracy

- **Własne obszary:** `backend/`, `data/`, `docker-compose.yml`, `README.md`; scraper, modele AI, dane i API.
- **Wspólne:** `CONTRACT.md` (zamrożony kontrakt API), próbki UKNF, integracja end-to-end, zgłoszenie w Hack Tribe, nagranie OBS, próba dla jury.
- **Stack:** Python, FastAPI, SQLite, httpx, Playwright, APScheduler, Ollama uruchomiona na hoście.
- **Asystent AI:** ChatGPT — ograniczaj przekazywany kontekst do `CONTRACT.md` i `backend/`; pliki `data/` udostępniaj tylko wtedy, gdy nie zawierają wrażliwych informacji i rzeczywiście są potrzebne.
- **Kluczowa zasada:** nie zmieniaj jednostronnie struktury odpowiedzi API ani zdarzeń WebSocket po zamrożeniu `CONTRACT.md`.

## 2. Harmonogram i zadania do odhaczenia

### Sobota 21.11 — etap 1 (11:15–12:30): dane i backend

**11:15–11:45 — razem z Aleksem**
- [ ] Odebrać próbki UKNF oraz załącznik do Modułu 2 z pendrive'a.
- [ ] Umieścić pliki w `data/uknf_samples/`; przejrzeć ograniczenia wykorzystywania/udostępniania danych i nie publikować materiałów poufnych.
- [ ] Przygotować niewrażliwe, syntetyczne lub zatwierdzone do demonstracji przypadki, w tym etykiety referencyjne dla FP/FN.
- [ ] Zamrozić wspólny `CONTRACT.md`, minimum: `GET /api/v1/incidents`; `risk_score` 0–1; `module_id` (1/2/3); `source_url`, `evidence_quotes`, `status`, `ground_truth_label` (jeśli znane), znacznik czasu; format `/ws/alerts`.
- [ ] Uzgodnić mechanizm uruchamiania analizy i aktualizacji statusów, jeżeli ma być klikalny w frontendzie; dopisać wymagane endpointy do kontraktu.

**11:45–12:30 — szkielet backendu**
- [ ] Utworzyć aplikację FastAPI w `backend/` i strukturę modułów.
- [ ] Skonfigurować SQLite i inicjalizację schematu bez usuwania istniejących danych.
- [ ] Wczytać lokalny **snapshot** danych podmiotów autoryzowanych KNF z udokumentowaną datą/źródłem; nie sugerować, że snapshot oznacza automatyczną weryfikację bieżącego statusu.
- [ ] Wystawić działający `GET /api/v1/incidents` ze stabilnym JSON zgodnym z kontraktem.
- [ ] Dodać CORS/routing dostosowany do adresów frontendu.

**Kryterium ukończenia:** API działa lokalnie, baza SQLite zapisuje/odczytuje incydenty, frontend może pobrać próbki.

### Sobota — etap 2 (12:30–16:00): scraper, trzy analizy AI, WebSocket

**12:30–14:30 — crawling i modele**
- [ ] Zaimplementować pobieranie stron przez `httpx` (timeouty, limity rozmiaru, kontrola redirectów, łagodne tempo żądań).
- [ ] Dodać Playwright jako fallback dla stron renderowanych przez JavaScript.
- [ ] Do testów zapewnić lokalny serwer statycznych mock-stron HTML odwzorowujących przykładowe treści społecznościowe i doradcze — bez udawania, że dane demonstracyjne są żywą platformą.
- [ ] Wprowadzić ochronę anty-SSRF: do publicznych URL tylko HTTP(S); blokować localhost, adresy prywatne/link-local, metadata IP i niedozwolone przekierowania; osobny tryb/whitelist dla lokalnych mock-źródeł; walidować adres także po rozwiązywaniu DNS i przy przekierowaniach.
- [ ] Używać rotacji User-Agent tylko w granicach regulaminów źródeł; nie omijać kontroli dostępu czy blokad serwisu.
- [ ] Uruchomić harmonogram/kolejkę cyklicznych zadań przez APScheduler, z zabezpieczeniem przed dublowaniem analiz.
- [ ] Spiąć **Moduł 1 — Finfluencerzy**: identyfikacja przekazu inwestycyjnego, źródło, oznaczenia reklamowe/konflikt interesów, sygnały ryzyka, cytaty.
- [ ] Spiąć **Moduł 2 — Proporcjonalność ryzyka**: ocena prezentacji ostrzeżeń o ryzyku w odniesieniu do przekazu; uwzględnić materiały UKNF.
- [ ] Spiąć **Moduł 3 — Shadow Advisory**: wykrywanie sugestii indywidualnych porad lub zarządzania aktywami pod pozorem edukacji.
- [ ] Dla każdego modułu przechowywać surowy `risk_score` w zakresie **0.00–1.00**, etykietę modułu, fragmenty dowodowe, tekst/URL źródłowy, znacznik czasu i informacje o zastosowanym modelu.
- [ ] Łączyć się z Ollama uruchomioną **natywnie na hoście**. Kontener backendu może używać `http://host.docker.internal:11434` po odpowiedniej konfiguracji host-gateway; sprawdzić OS i dostępność endpointu.
- [ ] Dodać fallback dla braku Ollama: wcześniej obliczone, wyraźnie oznaczone wyniki demonstracyjne z bazy.
- [ ] Nie obiecywać naukowej kalibracji `risk_score` bez walidacji; na demo traktować go jako wskaźnik modelu, a nie prawdopodobieństwo naruszenia prawa.

**14:30–15:00 — obiad i sync**
- [ ] Sprawdzić z Aleksem po jednym incydencie z każdego modułu (pola, cytaty, etykiety, `risk_score`).
- [ ] Zamknąć ewentualne rozbieżności między kodem a `CONTRACT.md`.

**15:00–16:00 — WebSocket**
- [ ] Wystawić `GET /ws/alerts` jako **połączenie WebSocket**.
- [ ] Emitować zdarzenia postępu crawlera (start, pobieranie, analiza, ukończenie/błąd) i alerty wysokiego ryzyka.
- [ ] W każdym komunikacie zachować pola z kontraktu: np. `type`, `timestamp`, `source`, `incident_id`, `message`, `risk_score` (w zależności od typu).
- [ ] Obsługiwać rozłączenie odbiorcy bez przerywania crawlera.
- [ ] Zweryfikować odbiór w frontendzie, nie tylko przez klienta testowego.

**Kryterium ukończenia:** analiza działa na lokalnych mock-źródłach, dane trafiają do SQLite/API, frontend odbiera alerty WebSocket.

### Sobota — etap 3 (16:00–20:00): kontenery, bezpieczeństwo, draft

**16:00–17:30 — wdrożenie**
- [ ] Przygotować `backend/Dockerfile` i `docker-compose.yml` spinający backend i frontend.
- [ ] Ustawić `extra_hosts`/`host-gateway` dla Linuksa, jeśli potrzebne, i prawidłowe połączenie z Ollama na hoście; opcjonalny profil `full-docker` tylko jako wariant, jeśli czas pozwoli.
- [ ] Zapewnić trwałość SQLite przez wolumen; ustawić healthcheck/startup checks i czytelne logi.
- [ ] Udokumentować wymagania: Python/Node tylko do dev, Docker Compose, Ollama oraz nazwa/model i sposób pobrania modelu.
- [ ] Uruchomić `pip-audit`, zapisać wynik; nie ukrywać ostrzeżeń (jeśli są, ocenić i podać wpływ).
- [ ] Napisać krótkie `README.md`: Quick Start, wymagane zmienne środowiskowe, kroki inicjalizacji danych, URL interfejsu, tryb demo i znane ograniczenia.
- [ ] Sprawdzić zgodność licencji bibliotek, modeli i materiałów z wymogiem **bezpłatnego wykorzystania komercyjnego**; zapisać źródła licencji i obowiązki w dokumentacji.

**17:30–18:30 — FEATURE FREEZE (wspólnie)**
- [ ] Uruchomić `docker compose up --build` po czystym checkoutcie i upewnić się, że demo działa w danym środowisku (start w 10 s jest celem, nie gwarancją: czas zależy od obrazów/modeli i sprzętu).
- [ ] Przejść sekwencję: scraper -> komunikat `/ws/alerts` -> wyniki modułów 1–3 -> suwak kalibracji w React.
- [ ] Zweryfikować fallback demonstracyjny bez zewnętrznego internetu.
- [ ] Po freeze poprawiać tylko usterki blokujące pokaz.

**18:30–19:50 — Hack Tribe (wspólnie)**
- [ ] Przekazać Aleksowi opis architektury, źródła danych, bezpieczeństwo, ograniczenia AI i wynik `pip-audit`.
- [ ] Dodać repozytorium, krótki opis techniczny i potwierdzić kompletność draftu.
- [ ] Sprawdzić, że repo nie zawiera `.env`, tokenów, danych osobowych, poufnych próbek ani artefaktów z niedozwoloną licencją.

**20:00 — twardy deadline:** draft zapisany/złożony w Hack Tribe zgodnie z zasadami wydarzenia.

### Sobota wieczór (20:30–22:30): nagranie i materiały

**20:30–22:30 — razem z Aleksem**
- [ ] Uruchomić stabilny backend i wybrane źródła demo przed nagrywaniem OBS.
- [ ] Przeprowadzić pełny flow na potrzeby materiału promocyjnego (docelowo do 3 minut, pod warunkiem zgodności z regulaminem).
- [ ] Pokazać w nagraniu wykrycie ryzyka, dowód cytatowy, źródło, log crawlera, trzy moduły i kalibrację FP/FN.
- [ ] Przygotować awaryjne rezultaty analizy zapisane w SQLite na wypadek niedostępności Ollama.
- [ ] Przekazać Aleksowi wyniki `pip-audit`, schemat architektury i informacje o licencjach do PDF.

### Niedziela 22.11 — etap 4 (08:30–11:00): kontrola i finał

**08:30–09:30 — test od zera**
- [ ] Wykonać czysty checkout repozytorium i uruchomić `docker compose up --build`.
- [ ] Sprawdzić endpointy, WebSocket, SQLite, Ollama lub fallback, lokalne mock-źródła.
- [ ] Z Aleksem sprawdzić konsolę przeglądarki (brak błędów); nie ukrywać błędów poprzez wyłączenie diagnostyki.
- [ ] Utworzyć tag Git `hacknation-2026-submission` na **zweryfikowanym** commicie i wypchnąć tag do zdalnego repo, jeśli wymagany.

**09:30–10:30 — próba generalna (wspólnie)**
- [ ] Zaprezentować na żywo architekturę hybrydową, trzy moduły analizy i drogę danych od źródła do incydentu.
- [ ] Przetestować plan B: demo offline z lokalnymi stronami i cache wyników.

**10:30–11:00 — finalne zgłoszenie (wspólnie)**
- [ ] Skontrolować repo, README, prezentację PDF, MP4 i formularz Hack Tribe.
- [ ] Zweryfikować linki, dostęp i faktyczne przesłanie materiałów.
- [ ] Zatwierdzić zgłoszenie **przed 11:00**.

## 3. Punkty zależności od Aleksa

| Kiedy | Co przekazujesz Aleksowi | Czego od niego oczekujesz |
|---|---|---|
| Do 11:45 | `CONTRACT.md` i przykładowe JSON | Potwierdzenia pól i tras |
| 12:30–14:30 | `GET /api/v1/incidents`, wyniki trzech modułów, etykiety prawdy | Weryfikacji renderowania i kalibracji |
| Do 15:00 | Schemat zdarzeń WebSocket | Implementacji logu i toastów |
| 16:00–17:30 | Porty/routing Compose i dostępność backendu | Działającego obrazu frontendu |
| Do 22:30 | `pip-audit`, licencje, opis architektury | Uwzględnienia w prezentacji PDF |
| Niedziela | Stabilny system po czystym starcie | Filmu i kompletnego zgłoszenia |

## 4. Definition of Done Krzysztofa

- [ ] FastAPI i SQLite działają oraz wystawiają uzgodniony kontrakt API.
- [ ] Scraper działa na zatwierdzonych mock-źródłach (i ostrożnie na publicznych URL), z ochroną anty-SSRF.
- [ ] Moduły 1–3 zwracają wyniki, fragmenty dowodowe i `risk_score` 0–1.
- [ ] `/ws/alerts` dostarcza live log i alerty do Reacta.
- [ ] Compose uruchamia oba serwisy, a Ollama na hoście lub fallback daje powtarzalne demo.
- [ ] `README.md`, `pip-audit`, dokumentacja licencji i bezpieczne repo są gotowe.
- [ ] Draft do 20:00 w sobotę, finalne zgłoszenie do 11:00 w niedzielę.
