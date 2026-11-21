# Ustandaryzowany Proces Wytwarzania Oprogramowania z Asystentami AI (`#InvestWatch`)

> Dokumentacja procesu inżynierskiego (kryterium oceny HackNation UKNF 2026 — innowacyjność wykonania rozwiązania).

## 1. Architektura współpracy: Contract-First & Izolacja Kontekstu

Zespół podzielił projekt na dwa niezależne, lekkie serwisy (`backend/` i `frontend/`) spięte pojedynczym źródłem prawdy — zamrożonym plikiem [CONTRACT.md](../CONTRACT.md).

1. **Zamrożenie kontraktu przed kodowaniem:** przed wygenerowaniem kodu modeli i UI zdefiniowano schemat JSON (`Incident`, `ViolatedRule`, `DomMetrics`), endpointy REST (`GET /api/v1/incidents`, `PATCH /api/v1/incidents/{id}/status`, `GET /api/v1/stats`, `POST /api/v1/crawl/trigger`) oraz zdarzenia WebSocket (`/ws/alerts`).
2. **Ograniczanie kontekstu przekazywanego asystentom AI:** asystent pracujący nad backendem otrzymywał wyłącznie `CONTRACT.md`, dokumenty regulacyjne UKNF oraz katalog `backend/`. Żadne poufne próbki ani sekrety `.env` nie były przekazywane do zewnętrznych narzędzi.
3. **Separacja warstw:** brak ciężkiego monorepo; każdy serwis posiada własny `Dockerfile` i niezależny pipeline testów/audytu (`pytest` + `pip-audit` dla Pythona, `npm audit` dla frontendu).

## 2. Standard jakości i weryfikacji (Human-in-the-Loop)

Każdy wygenerowany moduł przechodzi 4 obowiązkowe bramki kontrolne:

1. **Zgodność domenowa z załącznikami UKNF:** reguły Modułu 2 są mapowane 1:1 do 18 kryteriów z załącznika UKNF (`data/risk_criteria_rules.json` — art. 24 ust. 3 MiFID II, art. 44 ust. 2–8 rozp. del. 2017/565), a Moduł 3 do definicji z art. 76, 2 i 3 u.o.i.f.
2. **Testy automatyczne (`pytest`):**
   - `test_ssrf.py` — weryfikacja blokady SSRF (localhost, sieci prywatne RFC1918, adresy metadata chmury, niedozwolone schematy).
   - `test_modules.py` — testy deterministyczne Modułów 1, 2 i 3 na pozytywnych i negatywnych stronach demonstracyjnych (brak fałszywych alarmów dla materiałów zgodnych i biur podatkowych).
   - `test_api.py` — testy integracyjne REST, zmiany statusów, kalibracji FP/FN i powiadomień WebSocket `/ws/alerts`.
3. **Weryfikowalny łańcuch dostaw (Cybersec):** obowiązkowy audyt zależności (`pip-audit` / `npm audit`), uruchamianie kontenera jako użytkownik nieuprzywilejowany (`appuser`), izolacja zmiennych środowiskowych w `.env`.
4. **Rzetelność modeli AI w demo:** wszystkie modele uruchomieniowe działają w 100% on-premise (Ollama bez płatnych API), z jawnym oznaczeniem trybu fallback oraz zastrzeżeniem, że `risk_score` to wskaźnik priorytetyzacji dla analityka, a snapshot KNF ma jawną datę i źródło.
