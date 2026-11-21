"""Fictional evidence used by the explicit demo reset and live event endpoints."""
from datetime import datetime, timedelta, timezone

from app.ip_campaigns import add_note, campaign_id, insert

MAIN_IP = "185.220.101.45"
GROUPS = [
    (MAIN_IP, "AS24940 Hetzner Online GmbH", "DE", [
        ("QuantumAI Polska", "quantum-ai-invest-pl.com", "Obietnica stałej wypłaty po wpłacie depozytu.", 94),
        ("Orlen Invest AI", "orlen-invest-ai.pl", "Reklama wykorzystuje wizerunek spółki i zachęca do rozmowy z doradcą.", 88),
        ("Baltic Pipe Profit", "baltic-pipe-profit.pl", "Fałszywe udziały w gazociągu dla nowych klientów.", 91),
        ("QuantumAI Polska", "quantum-ai-invest-pl.com", "Konsultant żąda dopłaty za odblokowanie wypłaty.", 97),
        ("Orlen Invest AI", "orlen-invest-ai.pl", "Ponowna emisja reklamy lokaty z gwarancją zysku.", 89)]),
    ("91.214.44.18", "AS49505 OOO Network", "", [
        ("Weryfikacja PKO BP", "pko-weryfikacja.example", "SMS o konieczności odblokowania bankowości.", 91),
        ("BLIK Mobilny", "blik-potwierdz.example", "Formularz żąda podania kodu BLIK do odbioru zwrotu.", 85),
        ("Centrum PKO", "pko-weryfikacja.example", "Podszycie pod bank w reklamie odsyłającej do formularza.", 88),
        ("Odbiór BLIK", "blik-potwierdz.example", "Link do fałszywego potwierdzenia przelewu.", 84)]),
    ("45.142.212.90", "", "", [
        ("Obligacje dla seniora", "obligacje-premia.example", "Oferta rezerwacji obligacji po przedpłacie.", 84),
        ("KGHM Inwestycje", "kghm-inwestycje.example", "Fałszywy nabór do programu dywidendowego.", 90),
        ("Obligacje skarbowe", "obligacje-premia.example", "Podszycie pod publiczną emisję obligacji.", 86)]),
    ("192.0.2.10", "", "", [("Portfel jutra", "portfel-jutra.example", "Niejasne opłaty w reklamie aplikacji.", 47)]),
    ("198.51.100.20", "", "", [("Kurs inwestora", "kurs-inwestora.example", "Zgłoszenie reklamy płatnego szkolenia.", 36)])]


def seed(c):
    c.execute("DELETE FROM campaign_notes")
    c.execute("DELETE FROM case_reports")
    start = datetime.now(timezone.utc) - timedelta(hours=14)
    i = 0
    for ip, asn, country, cases in GROUPS:
        for title, domain, content, risk in cases:
            evidence = dict(asn=asn, country=country, aliases=[title])
            if ip == MAIN_IP:
                evidence.update(phones=[["+48 22 100 20 30","+48 22 100 20 31"][i%2]],
                                bank_accounts=["PL61 1090 1014 0000 0712 1981 2874"])
            insert(c, title=title, content=content, domain=domain, ip_address=ip, source=
                   ("CITIZEN_FORM","CRAWLER","ANALYST_PANEL","EXTERNAL_API")[i%4],
                   risk_score=risk, human_reviewed=i in (1,3,5,8,10), evidence=evidence,
                   technical={"demo":True}, created_at=(start+timedelta(hours=i)).isoformat(timespec="seconds").replace("+00:00","Z"))
            i += 1
    for message in ("Porównano domeny i rachunek podany w zgłoszeniach.",
                    "Zabezpieczono materiały dotyczące trzech wariantów reklamy."):
        add_note(c,campaign_id(MAIN_IP),"Analityk Nadzoru",message)
    return i


def simulate(c):
    return insert(c, title="QuantumAI VIP — kolejna reklama", content="Nowa oferta gwarantowanej wypłaty po wpłacie depozytu.",
                  domain="quantum-ai-vip24.pl", ip_address=MAIN_IP, source="CRAWLER",risk_score=96,
                  evidence={"aliases":["QuantumAI VIP"],"asn":"AS24940 Hetzner Online GmbH","country":"DE"},
                  technical={"demo":True})

