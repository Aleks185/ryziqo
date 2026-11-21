# INVESTWATCH — odbiór etapu 2, 21 listopada 2026

## Zakres wdrożenia

Rejestr korzysta z tej samej bazy SQLite co incidents, analysis_cache, content_snapshots, crawl_jobs i watch_targets. Tabela threat_reports wiąże analizę ze zgłoszeniem, kampanią i decyzją analityka. report_quota obsługuje limit zgłoszeń, a intel_config konfigurację rejestru. Nowe widoki wykorzystują nagłówek aplikacji, komponenty Panel i RiskScore oraz dotychczasowe style tabel, pól i przycisków.

Panel udostępnia wyszukiwanie zgłoszeń, notatki i statusy, kampanie ze zbiorczą zmianą statusu oraz diagnostykę kolejki i modelu. Pulpit prezentuje wskaźniki i pięć ostatnich zgłoszeń. Z widoku szczegółów można skopiować paczkę dowodową CERT / KNF.

## Próby akceptacyjne

Pomiary wykonano na osobnej bazie, z obrazami Docker użytymi we wdrożeniu i lokalnym modelem gemma3:4b. Najpierw analityk potwierdził testowe przypadki. Tabela podaje czas pojedynczego lokalnego żądania w ostatniej serii.

| Próba | Wynik | Czas |
|---|---|---:|
| Pierwsza analiza tekstu | Ollama | 22,97 s |
| Ponowne zgłoszenie tekstu | Fast-Path | 13,01 ms |
| URL w potwierdzonej domenie | Fast-Path | 8,75 ms |
| Wymuszenie pełnej analizy tekstu | Ollama | 23,11 s |
| Ponownie skompresowany obraz | Fast-Path | 14,15 ms |

Wszystkie trzy trafienia spełniły cel 50 ms w tej próbie. Wyniki nie określają czasu odpowiedzi pod obciążeniem. Osobny test blokował dostęp do kolejki i sprawdzania Ollamy podczas trafienia. Diagnostyka testowa zarejestrowała trzy trafienia i dwie kampanie. Podczas rzeczywistego pobrania strony zapisano dane połączenia i odczytano ASN 13335 oraz kod kraju CA.

Testy backendu: 142 zaliczone, jedno ostrzeżenie o przestarzałym API Starlette. Testy Playwright w Chromium sprawdziły rozwijanie menu, przejścia między widokami, wyszukiwanie i rzeczywistą zawartość schowka przy szerokościach 390 i 1440 px. Spójność interfejsu sprawdzono funkcjonalnie i na poziomie użytych komponentów. Nie wykonano porównania pikselowego z archiwalnymi zrzutami.

## Interpretacja i eksploatacja

Fast-Path korzysta z przypadków oznaczonych przez analityka jako potwierdzone. Wysoki wynik modelu sam nie zatwierdza zgłoszenia. Dla platform współdzielonych wymagane jest ściślejsze dopasowanie adresu. Dla obrazów próg odległości Hamminga wynosi 6. Przy braku trafienia powiązane historyczne zgłoszenia mogą zasilić kontekst modelu. Powiązanie przez wspólny IP może objąć różne strony na tym samym hostingu i wymaga interpretacji przez analityka.

Metadane zależą od rodzaju materiału. Tekst bez adresu oraz sam screenshot mogą nie mieć domeny, IP serwera ani przekierowań. IP serwera pochodzi ze zweryfikowanego połączenia podczas pobierania URL. Geolokalizacja opisuje infrastrukturę i jest przybliżona. Opcjonalne ustalanie wieku domeny przez RDAP pozostaje wyłączone.

Limit domyślny to 30 zgłoszeń na minutę na pseudonim IP. Aplikacja ufa nagłówkowi adresu klienta wyłącznie od skonfigurowanego proxy. Surowy IP i User-Agent są czyszczone po 7 dniach, a pseudonim HMAC po 30 dniach w okresowym przebiegu czyszczenia. Widok szczegółów udostępnia maskowany adres. Testy objęły podszyty nagłówek proxy, limit żądań i zabezpieczenia pobierania URL.

Do przetwarzania obrazu wykorzystano Pillow (MIT-CMU), do domen tldextract (BSD-3-Clause), a do odczytu baz hostingu maxminddb (Apache-2.0). Sygnatura percepcyjna jest obliczana lokalnie. Dane hostingu: [DB-IP Lite](https://db-ip.com/db/lite.php), wydanie 2026-11, CC BY 4.0.
