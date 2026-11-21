# INVESTWATCH — fundament frontendu panelu analitycznego dla UKNF
Panel dla analityków nadzoru do wykrywania problematycznych reklam inwestycyjnych, finfluencerów i ukrytego doradztwa, z cytatami dowodowymi i kalibracją progu ryzyka.
Emergent przygotowuje gotowy do rozwoju frontend oraz projekt kontraktu API; Krzysztof rozwija frontend, Aleks dostarcza backend z Ollamą i silnikiem scrapingu.

## Dla kogo
- **Analityk UKNF** — przegląda incydenty, czyta uzasadnienie i cytaty, zmienia status, drukuje raport A4.
- **Jury HackNation** — ogląda demo na rzutniku i na filmie (do 3 min), weryfikuje zgodność z 3 modułami UKNF, działanie kalibracji, WebSocketów oraz czystość konsoli przeglądarki.
- **Zespół (Krzysztof, Aleks)** — rozwija i integruje komponenty według `CONTRACT.md`.

## Uwagi krytyczne do planu (ustalone przez zespół)
1. **Podział ról ujednolicony:** Krzysztof = frontend, Aleks = backend + scraper + Ollama. Starsze notatki z odwrotnym przypisaniem są nieaktualne.
2. **Prawdziwa analiza AI w podglądzie Emergent nie jest możliwa** przy zakazie płatnych usług AI: Ollama działa lokalnie i nie jest osiągalna z chmury. Realna analiza AI oraz OCR działają po podłączeniu frontendu do backendu Aleksa; w podglądzie Emergent działa wyraźnie oznaczony **tryb DEMO**.
3. **Tryb DEMO nie udaje AI:** jawny analizator regułowy (słowa-klucze dla Modułów 1, 2 i 3). Cytaty wycinane dosłownie z wklejonego tekstu. Każdy wynik z etykietą „DEMO — heurystyka, nie AI”.
4. **Czysta konsola w trybie DEMO:** gdy backend nie odpowiada, klient WebSocket nie łączy się w pętli (zero czerwonych błędów `ws://` w DevTools). Brak zbędnych `console.log()`.
5. **`CONTRACT.md` (DRAFT):** `/api/v1/…`, `/ws/alerts`, `risk_score` 0.00–1.00, sekcja **„AI-Driven Development Workflow”**. Zamrożenie wspólnie przez Krzysztofa i Aleksa; frontend dostosuje się do zmian.
6. **Endpoint zmiany statusu** opcjonalny — bez niego zmiana statusu działa lokalnie z etykietą „DEMO”.
7. **Rejestry KNF / lista ostrzeżeń** — po stronie backendu. Frontend pokazuje podmiot, status w rejestrze, źródło, datę sprawdzenia; w DEMO: „nie sprawdzono — brak połączenia z backendem”.

## Kluczowe funkcje i doświadczenie
- **Dashboard** — filtr Moduł 1 (Finfluencerzy i podmioty trzecie) / Moduł 2 (Zgodność informacji o ryzyku) / Moduł 3 (Shadow Advisory) / Wszystkie; karty liczników tylko z rzeczywiście zapisanych incydentów; kompaktowy wykres trendów (Recharts) z podziałem na moduły; lista incydentów z wynikiem, modułem, źródłem, datą i statusem.
- **Formularz analizy (3 kanały)** — zakładki Tekst / Adres URL / Obraz-Zrzut ekranu (PNG/JPEG/WebP, multipart/form-data); wybór modułów; przycisk **„Załaduj przykład UKNF”**; stany: trwa analiza, sukces, błąd, brak backendu. Zakładka Obraz w DEMO: *„Analiza OCR obrazów wymaga połączenia z lokalnym backendem (Tesseract/Ollama)”*.
- **Szczegóły incydentu** — `risk_score`, uzasadnienie, cytaty z podświetleniem w materiale źródłowym, informacje o podmiocie, źródło/URL, znacznik czasu, status, adnotacja „Wynik AI jest wskazówką do weryfikacji przez analityka, nie oceną prawną”.
- **Widok wydruku A4** — `@media print` ukrywa nawigację i banery; nagłówek InvestWatch, dane, cytaty, hash/źródło, miejsce na datę i podpis analityka.
- **Panel kalibracji Threshold** — suwak 0.00–1.00 przelicza lokalnie, bez sieci i AI; macierz TP/TN/FP/FN, precyzja/czułość, wykres FP/FN w funkcji progu. Tylko rekordy z etykietą referencyjną; liczba rekordów bez etykiety pokazana jawnie.
- **Live Crawler Log** — zdarzenia z `/ws/alerts` (oraz lokalne zdarzenia analizy w DEMO) z czasem i typem; wskaźnik online/offline/DEMO; reconnect tylko przy aktywnym backendzie.
- **Powiadomienia** — toast przy `risk_score >= 0.70`, bez duplikatów.
- **Przełącznik PL / EN** w nagłówku.
- **Baner DEMO** zawsze widoczny przy braku backendu.

## Przepływ użytkownika
1. Dashboard → status połączenia, liczniki, wykres trendów.
2. Formularz → „Załaduj przykład UKNF” lub tekst/URL/zrzut → moduły → „Analizuj”.
3. Incydent zapisany → lista, Live Crawler Log, toast przy wysokim ryzyku.
4. Szczegóły → uzasadnienie i cytaty → zmiana statusu → druk A4.
5. Kalibracja → suwak → natychmiastowa zmiana macierzy i wykresu.

## UI/UX — charakter
- Urzędowy, poważny, jasny: biel, chłodne szarości, głęboki granat; statusy: czerwień/bursztyn/zieleń.
- Typografia instytucjonalna, `tabular-nums` w wynikach, czcionki OFL.
- Gęste, czytelne tabele i cytaty, bez gradientów i ozdobników.
- Logotyp InvestWatch w SVG (oko / lupa nad wykresem).
- Czytelny na rzutniku, filmie i wydruku; responsywny, obsługa klawiaturą, widoczny focus.

## Fazy realizacji
**Faza 1 — MVP (budowane teraz)**
- `CONTRACT.md` (DRAFT) z przykładowym incydentem, zdarzeniami WebSocket i opisem procesu pracy z AI.
- Kompletny frontend: Dashboard z trendami, formularz (Tekst/URL/Obraz + przykład), lista i szczegóły, druk A4, kalibracja, Live Crawler Log, toasty, PL/EN, logotyp.
- Warstwa komunikacji przez jeden konfigurowalny adres ze zmiennej środowiskowej (`VITE_API_URL` po przeniesieniu do Vite, domyślnie `http://localhost:8000/api/v1`, automatyczne ws/wss), pod Docker Compose (komunikacja z przeglądarki).
- Tryb DEMO: wbudowany w przeglądarkę silnik zapasowy realizujący kontrakt, analizator regułowy, zapis incydentów w localStorage, cicha obsługa braku WebSocketa.
- 6 przykładowych tekstów reklam (oznaczonych jako przykładowe) z `ground_truth`.

**Faza 2 — integracja**
- Podłączenie backendu Aleksa (FastAPI + SQLite + scraper + Ollama), dopasowanie do zamrożonego kontraktu, test na próbkach UKNF.
- `Dockerfile` (multi-stage) frontendu pod `docker-compose.yml` Aleksa.

**Faza 3 — finał hackathonu**
- Szlify po feature freeze, `npm audit --omit=dev`, weryfikacja konsoli, materiały do PDF i filmu.

## Założenia
- Role: Krzysztof — frontend, Aleks — backend + scraper + Ollama.
- Emergent nie tworzy backendu produkcyjnego; DEMO jest tymczasowe i działa w przeglądarce.
- Bez płatnych usług AI; realna analiza tylko przez Ollamę u Aleksa.
- React + Tailwind + Recharts + natywny WebSocket, przenośne do Vite (podgląd Emergent działa na własnej konfiguracji Reacta, więc w podglądzie zmienna nazywa się inaczej).
- Licencje MIT/ISC/OFL.
- Bez logowania.
- Bez zdjęć stockowych; tylko logotyp i ikony.
- Próg toastów 0.70 (konfigurowalny).
- Domyślny język: polski.
