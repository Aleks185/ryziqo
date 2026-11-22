"""Demo data for campaign detection: real scenarios through the running API, with PASS/FAIL checks.

Every scenario goes through the same endpoints as the UI (analysis, analyst review, campaigns), so the
data left behind shows the mechanisms from docs/kampanie-fejkow.md working end to end:
campaign grouping, fast path, anti-obfuscation, URL canonicalization, neutral domains, revoking
a verdict, module coverage, detaching a report, campaign notes / active filter, campaign clones
and the relationship graph.

Standard library only, so it runs on the host against docker compose:

    python backend/scripts/seed_campaign_demo.py                       # http://localhost:8000/api/v1
    python backend/scripts/seed_campaign_demo.py --api http://localhost:3000/api/v1

Each run uses a fresh tag in texts and domains, so runs are independent and can be repeated.
With Ollama every full analysis takes longer (module 2 only by default, see --modules).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000/api/v1"
MODULES = [2]
RESULTS: list[tuple[bool, str]] = []


def call(method: str, path: str, body: dict | None = None, *, timeout: float = 900) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    for _ in range(10):
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:  # REPORT_LIMIT_PER_MINUTE
                wait = int(exc.headers.get("Retry-After", "60"))
                print(f"    (limit zgłoszeń na minutę — czekam {wait} s)")
                time.sleep(wait)
                continue
            raise SystemExit(f"{method} {path} → HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}")
    raise SystemExit(f"{method} {path}: limit zgłoszeń nie ustąpił")


def analyze(content: str, *, channel: str = "analyst_panel", modules: list[int] | None = None, **extra) -> dict:
    body = {"content": content, "module_ids": modules or MODULES, "source_channel": channel, **extra}
    return call("POST", "/analyze/text", body)


def report(report_id: str) -> dict:
    return call("GET", f"/intelligence/reports/{report_id}")


def rid(result: dict) -> str:
    return result["report"]["report_id"]


def campaign_of(result: dict) -> str:
    return report(rid(result))["campaign_id"]


def check(ok: bool, label: str) -> bool:
    RESULTS.append((ok, label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def section(title: str) -> None:
    print(f"\n== {title}")


def main() -> int:
    global API, MODULES
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=API, help="adres API (domyślnie %(default)s)")
    parser.add_argument("--modules", default="2", help="moduły pełnej analizy, np. 2 lub 1,2,3 (domyślnie %(default)s)")
    args = parser.parse_args()
    API = args.api.rstrip("/")
    MODULES = sorted({int(m) for m in args.modules.split(",")})

    health = call("GET", "/health", timeout=10)
    tag = secrets.token_hex(3)
    print(f"API {API} · status {health.get('status')} · Ollama {health.get('ollama_available', '?')} · tag przebiegu: {tag}")
    campaigns: dict[str, str] = {}

    # --- 1. Campaign by a scam domain -------------------------------------------------------------
    section("1. Kampania „BTC Gwarant” — trzy różne reklamy, jedna domena oszustów")
    site = f"btc-gwarant-{tag}.xyz"
    ads = [
        f"Gwarantowany zysk 300% w 30 dni! Bot BTC zarabia za Ciebie. Zarejestruj się: https://{site}/start",
        f"Tylko dziś: wpłać 1000 zł, wypłać 9000 zł. Bez ryzyka, pieniądze wracają. Wejdź https://{site}/promo?utm_source=fb",
        f"Znany ekonomista zdradza sekret: system BTC, który podwaja kapitał co tydzień → https://www.{site}/vip#form",
    ]
    btc = [analyze(text) for text in ads]
    groups = {campaign_of(r) for r in btc}
    campaigns["btc"] = next(iter(groups))
    check(len(groups) == 1, f"3 reklamy z linkiem do {site} są w jednej kampanii")

    # --- 2. Fast path after confirming the campaign -----------------------------------------------
    section("2. Potwierdzenie kampanii → szybka ścieżka dla kolejnych zgłoszeń obywateli")
    updated = call("PATCH", f"/intelligence/campaigns/{campaigns['btc']}",
                   {"verdict_status": "confirmed_fake", "analyst_notes": f"[demo {tag}] Potwierdzona kampania BTC Gwarant."})
    check(updated["updated"] == 3, "jedno kliknięcie oceniło 3 zgłoszenia kampanii")
    incident = btc[0]["items"][0]["id"]
    inc = call("GET", f"/incidents/{incident}")
    check(inc["status"] == "confirmed" and inc["ground_truth_label"] is True,
          "werdykt kampanii trafił do incydentu (status confirmed + etykieta) — uczy wykrywanie klonów")
    hits = [analyze(ads[0], channel="public_form") for _ in range(2)]
    check(all(h["report"]["result_origin"] == "fast_path" for h in hits), "ponowne zgłoszenia obywateli: fast_path bez LLM")
    check(hits[1]["report"]["summary"].count("Dopasowano do potwierdzonego") == 1,
          "prefiks „Dopasowano…” występuje raz (nie piętrzy się)")
    check(report(rid(hits[1]))["matched_id"] == rid(btc[0]), "źródłem werdyktu jest pełna analiza, nie kopia fast_path")

    # --- 3. Obfuscation ---------------------------------------------------------------------------
    section("3. Obfuskacja — znaki zero-width i cyrylica nie omijają bazy")
    obfuscated = ads[0].replace("Gwarantowany", "Gwa​rantowany").replace("BTC", "ВТС").replace("zysk", "z​ysk")
    hit = analyze(obfuscated, channel="public_form")
    check(hit["report"]["result_origin"] == "fast_path", "tekst z „ВТС” (cyrylica) i zero-width → fast_path")

    # --- 4. Platform URL with tracking params -----------------------------------------------------
    section("4. Ten sam post na Facebooku z parametrami śledzącymi")
    post = f"https://www.facebook.com/ads/library/?id=99{int(tag, 16)}"
    first = analyze(f"Inwestycja w złoto z gwarancją 20% miesięcznie, zapisy w komentarzu: {post}")
    call("PATCH", f"/intelligence/reports/{rid(first)}", {"verdict_status": "confirmed_fake"})
    again = analyze(f"Ktoś mi to wysłał, czy to oszustwo? {post}&fbclid=IwAR{tag}&utm_source=messenger", channel="public_form")
    check(again["report"]["result_origin"] == "fast_path", "inny tekst, ten sam post (+fbclid, utm_*) → fast_path")
    check(campaign_of(again) == campaign_of(first), "oba zgłoszenia w jednej kampanii")
    other_post = analyze(f"Inny post na Facebooku o tym samym: https://www.facebook.com/ads/library/?id=77{int(tag, 16)}")
    check(campaign_of(other_post) != campaign_of(first), "inny post na tej samej platformie to osobna grupa")

    # --- 5. Neutral domains -----------------------------------------------------------------------
    section("5. Domeny neutralne (KNF, skracacze) nie sklejają niepowiązanych zgłoszeń")
    knf_a = analyze(f"Przeczytaj komunikat https://www.knf.gov.pl/komunikaty/{tag}-1 o nowych zasadach nadzoru.")
    knf_b = analyze(f"Lista ostrzeżeń publicznych jest tu: https://www.knf.gov.pl/ostrzezenia?ref={tag}, warto sprawdzać.")
    check(campaign_of(knf_a) != campaign_of(knf_b), "dwa teksty z linkami do knf.gov.pl → różne grupy")
    short_a = analyze(f"Zarabiaj 5000 zł dziennie, link: https://bit.ly/{tag}a")
    short_b = analyze(f"Przepis na sernik babci, szczegóły: https://bit.ly/{tag}b")
    check(campaign_of(short_a) != campaign_of(short_b), "dwa różne linki bit.ly → różne grupy")
    mixed = analyze(f"Zarejestrowani w https://www.knf.gov.pl — dołącz do nas: https://{site}/knf-certyfikat")
    meta = report(rid(mixed))
    check(meta["canonical_domain"] == site, f"tekst z linkiem KNF + linkiem scamu dostaje domenę scamu ({meta['canonical_domain']})")
    check(meta["campaign_id"] == campaigns["btc"], "…i dołącza do kampanii BTC Gwarant")

    # --- 6. Revoking a verdict + module coverage --------------------------------------------------
    section("6. Korekta werdyktu i zakres modułów")
    lottery = f"Wygrałeś iPhone {tag}! Opłać tylko 9,99 zł za wysyłkę i zainwestuj resztę w nasz fundusz z gwarancją zysku."
    base = analyze(lottery)
    call("PATCH", f"/intelligence/reports/{rid(base)}", {"verdict_status": "confirmed_fake"})
    if MODULES != [1, 2, 3]:
        wider = analyze(lottery, modules=[1, 2, 3])
        check(wider["report"]["result_origin"] != "fast_path",
              f"werdykt dla modułów {MODULES} nie jest użyty dla żądania [1, 2, 3] (pełna analiza)")
    check(analyze(lottery)["report"]["result_origin"] == "fast_path", "to samo żądanie co potwierdzone → fast_path")
    newer = analyze(lottery, force_full=True)
    call("PATCH", f"/intelligence/reports/{rid(newer)}",
         {"verdict_status": "false_positive", "analyst_notes": f"[demo {tag}] Korekta: konkurs jest prawdziwy."})
    check(analyze(lottery)["report"]["result_origin"] != "fast_path", "nowsza decyzja false_positive cofa szybką ścieżkę")

    # --- 7. Detach ------------------------------------------------------------------------------------
    section("7. Ręczne odłączenie błędnie przypisanego zgłoszenia")
    forex = f"forex-signal-{tag}.com"
    fx = [analyze(f"Sygnały forex {n}: 95% skuteczności, gwarancja zwrotu. https://{forex}/{n}") for n in ("a", "b", "c")]
    group = campaign_of(fx[0])
    moved = call("POST", f"/intelligence/reports/{rid(fx[2])}/detach")["campaign_id"]
    check(moved != group, "odłączone zgłoszenie ma nową grupę")
    later = analyze(f"Kolejna reklama sygnałów forex, 99% skuteczności: https://{forex}/nowa i https://{forex}/c")
    check(campaign_of(later) == group and report(rid(fx[2]))["campaign_id"] == moved,
          "kolejne pasujące zgłoszenie nie wciąga odłączonego z powrotem")
    campaigns["forex"] = group

    # --- 8. Rejected campaign + active filter --------------------------------------------------------
    section("8. Kampania odrzucona w całości znika z widoku „Tylko aktywne”")
    legit = f"oszczednosci-{tag}.pl"
    ok = [analyze(f"Poradnik: jak odkładać 10% pensji na lokacie. Kalkulator: https://{legit}/{n}") for n in ("x", "y")]
    campaigns["legit"] = campaign_of(ok[0])
    call("PATCH", f"/intelligence/campaigns/{campaigns['legit']}",
         {"verdict_status": "false_positive", "analyst_notes": f"[demo {tag}] Treść edukacyjna, bez naruszeń."})
    active = {c["campaign_id"] for c in call("GET", "/intelligence/campaigns?active_only=true&limit=500")}
    everything = {c["campaign_id"]: c for c in call("GET", "/intelligence/campaigns?limit=500")}
    check(campaigns["legit"] not in active and campaigns["legit"] in everything, "odrzucona kampania: ukryta w aktywnych, widoczna we wszystkich")
    btc_card = everything.get(campaigns["btc"], {})
    check(btc_card.get("domain") == site and btc_card.get("confirmed_count", 0) >= 3,
          f"karta BTC Gwarant: domena {btc_card.get('domain')}, potwierdzone {btc_card.get('confirmed_count')}, "
          f"nowe {btc_card.get('new_count')}, notatka: {btc_card.get('analyst_notes')!r}")

    # --- 9. Campaign clone on another domain ---------------------------------------------------------
    section("9. Klon potwierdzonej kampanii na innej domenie (pamięć incydentów)")
    clone_text = ("Ziomki, ta apka to sztos, w miesiąc z tysiaka zrobiłem trzy, kasa sama wpada na konto. "
                  "Kto chce, niech pisze na priv, podeślę swój numerek do rejestracji i dostaniecie extra hajs na start. "
                  "Rejestracja: https://{host}/ref?code=" + tag)
    original = analyze(clone_text.format(host=f"apka-sztos-{tag}.xyz"))
    call("PATCH", f"/intelligence/reports/{rid(original)}", {"verdict_status": "confirmed_fake"})
    clone = analyze(clone_text.format(host=f"kasa-na-start-{tag}.top") + " Link aktualny, spieszcie się!")
    rules = [r for item in clone["items"] for r in item["violated_rules"] if r["rule_id"] == "CAMPAIGN_CLONE_MATCH"]
    original_ids = {i["id"] for i in original["items"]}
    check(bool(rules) and bool(original_ids & set(rules[0].get("related_incident_ids", []))),
          "przeredagowana kopia na innej domenie dostaje CAMPAIGN_CLONE_MATCH wskazujący oryginał")
    check(campaign_of(clone) != campaign_of(original), "klon nie jest sklejony w kampanię (inna domena, inna treść)")

    graph = call("GET", "/intelligence/graph?min_score=0&limit=500")
    clone_ids = {i["id"] for i in clone["items"]}
    edges = [e for e in graph["edges"] if e["type"] == "clone_of"
             and e["source"].removeprefix("incident:") in clone_ids and e["target"].removeprefix("incident:") in original_ids]
    check(bool(edges), "mapa powiązań: krawędź clone_of klon → oryginał")
    in_campaign = [e for e in graph["edges"] if e["type"] == "in_campaign" and e["target"] == f"campaign:{campaigns['btc']}"]
    check(len(in_campaign) >= 2, f"mapa powiązań: węzeł kampanii BTC Gwarant z {len(in_campaign)} incydentami")

    # --- Summary ------------------------------------------------------------------------------------
    passed = sum(ok for ok, _ in RESULTS)
    print(f"\nWynik: {passed}/{len(RESULTS)} PASS")
    for ok_, label in RESULTS:
        if not ok_:
            print(f"  FAIL: {label}")
    ui = API.removesuffix("/api/v1").replace(":8000", ":3000")
    print(f"\nDo obejrzenia w UI ({ui}):")
    print(f"  Kampanie:           {ui}/campaigns")
    print(f"  BTC Gwarant:        {ui}/reports?campaign={campaigns['btc']}")
    print(f"  Forex (odłączanie): {ui}/reports?campaign={campaigns['forex']}")
    print(f"  Mapa powiązań:      {ui}/graph")
    print(f"  Szukaj w bazie zgłoszeń po tagu przebiegu: {tag}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
