"""Evidence-backed Polish investment solicitation signals for Module 2."""
import re
from dataclasses import dataclass
from decimal import Decimal

from app.models import ViolatedRule


def words(expression: str) -> re.Pattern:
    return re.compile(r"\b(?:" + expression + r")\b", re.IGNORECASE)


PAY = words(r"wpłać|wpłacić|przelej|przelać|dopłać|opłać|uiść|dokonaj wpłaty|wymagana jest (?:wpłata|dopłata)")
# Investment offers may request a specific stake without using the verb "wpłać".
INVEST_AMOUNT = words(
    r"(?:(?:zacznij|rozpocznij)\s+od\s+|zainwestuj\s+(?:(?:minimalną|początkową)\s+kwotę\s+|kwotę\s+|"
    r"(?:tylko|zaledwie|minimum|od)\s+)?)"
    r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?\s*(?:zł(?:otych)?|pln|eur|usd)"
)
COMMIT_FUNDS = re.compile(f"(?:{PAY.pattern}|{INVEST_AMOUNT.pattern})", re.I)
FEE = words(r"podat(?:ek|ku)|prowizj[ęai]|opłat[ęay]|kaucj[ęai]")
RELEASE = words(r"(?:aby|żeby|by) (?:móc )?(?:wypłacić|odebrać środki|odblokować (?:wypłatę|środki))|warunkiem wypłaty|przed wypłatą|wypłata (?:będzie )?możliwa (?:dopiero )?po")
FINANCE = words(r"inwest\w*|depozyt\w*|zysk\w*|zarob\w*|zarób|zarab\w*|handl\w* na giełdzie|rachun\w* maklersk\w*")
REMOTE = words(r"(?:zainstaluj|uruchom|pobierz) (?:program |aplikację )?(?:anydesk|teamviewer|rustdesk|pulpit zdalny)|udostępnij (?:swój )?ekran")
ACCESS = words(r"(?:podaj|wyślij|przekaż|udostępnij) (?:\w+ ){0,3}(?:kod|identyfikator|hasło) (?:połączenia|sesji|dostępu)|(?:zezwól|pozwól) na (?:zdalne )?(?:sterowanie|dostęp)")
CERTAINTY = words(
    r"zero ryzyka|bez (?:żadnego )?ryzyka|100\s*%\s*(?:skuteczności|pewności)|"
    r"gwarantujemy (?:ci )?(?:zysk|dochód|zwrot)|gwarantowan[ey] (?:zysk|dochód|zwrot)|"
    r"(?:zysk|dochód) jest gwarantowany|"
    r"(?:daje(?:my)?|zapewnia(?:my)?|oferuje(?:my)?)\s+(?:ci\s+)?"
    r"(?:100\s*%\s*|pełną\s+)?gwarancj[ęia]\s+(?:zysku|dochodu)"
)
# At least 10% promised in a day or up to one week; retain the original wording as evidence.
ASSURED_SHORT_RETURN = words(
    r"(?:pewny|gwarantowany) (?:zwrot|zysk)\s+(?:w wysokości\s+)?"
    r"(?:[1-9]\d+|[1-9]\d{0,2}(?:\s\d{3})+)(?:[.,]\d+)?\s*%\s+"
    r"(?:w\s+(?:ciągu\s+)?(?:tydzień|tygodnia|dzień|dobę|[2-7]\s+dni)|tygodniowo|dziennie)"
)
DEADLINE = words(r"(?:tylko |jeszcze )?do północy|link zniknie|(?:po)?zosta(?:ło|ły) (?:tylko )?\d+ (?:(?:woln(?:ych|e)|ostatni(?:ch|e)) )?miejsc(?:a)?|ostatnia szansa na wpłatę")
CRYPTO_FORECAST = words(
    r"(?:token|kryptowaluta|bitcoin|kurs tokena|cena tokena)\s+"
    r"(?:wzrośnie|zyska|podrożeje)\s+(?:o\s+)?\d+(?:\s\d{3})*(?:[.,]\d+)?\s*%\s+"
    r"(?:w\s+(?:(?:najbliższy|ten)\s+)?weekend|"
    r"w\s+(?:ciągu\s+)?\d+\s+(?:godzin\w*|dni)|(?:jeszcze\s+)?dziś|jutro)"
)
OFFER_EXPIRY = words(
    r"oferta\s+(?:jest\s+)?(?:ważna|dostępna)\s+(?:tylko|jeszcze)\s+"
    r"(?:przez\s+(?:najbliższą\s+godzinę|godzinę|\d+\s+(?:godzin\w*|minut\w*))|do północy)"
)
EARNINGS_STORY = words(
    r"(?:zarobił[ao]?|zarobiłem|zarobiłam|zyskał[ao]?)\s+(?:aż\s+|ponad\s+)?"
    r"\d+(?:\s\d{3})*(?:[.,]\d{1,2})?\s*(?:zł(?:otych)?|PLN)\s+"
    r"w\s+(?:ciągu\s+)?(?:(?:\d{1,2}|dwa|dwie|kilka|trzy|cztery)\s+)?"
    r"(?:dzień|dni|tydzień|tygodnie|tygodni|godzin[ęy]?)"
)
SECRET_INVESTMENT = words(
    r"(?:tajn[ayą]|sekretn[ayą]|ukryt[ayą])\s+(?:system|metod[ęa]|strategi[ęa]|program)"
    r"\s+(?:inwestycyjn\w*|inwestowania|zarabiania)"
)
EXPIRING_LINK = words(
    r"(?:kliknij|sprawdź|wejdź)(?: w link)?[,\s]+(?:zanim|nim)\s+"
    r"(?:ta\s+)?(?:strona|link|oferta)\s+(?:zniknie|wygaśnie)"
)
MANAGED_TRADING = words(
    r"(?:handluje|inwestuje) (?:za ciebie|w twoim imieniu)|"
    r"(?:bot|algorytm|robot|sztuczna inteligencja) (?:automatycznie )?(?:handluje|inwestuje)"
)
PUBLIC_PLATFORM = words(
    r"(?:narodow|państwow|rządow)\w*\s+(?:platform|program)\w*\s+"
    r"(?:surowcow|inwestycyjn|energetyczn)\w*"
)
PAYOUT_NUMBER = r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?"
PAYOUT_CURRENCY = r"(?:zł(?:otych)?|pln|eur|usd)"
ALGORITHM_REQUEST = words(r"(?:włącz|uruchom|aktywuj)\s+(?:nasz\s+)?(?:algorytm|automat|bot[a]?)")
STAKE = words(rf"(?:wpłać|zainwestuj|przelej)\s+(?:tylko\s+)?({PAYOUT_NUMBER})\s*({PAYOUT_CURRENCY})")
ACCOUNT_CREDIT = words(
    r"na (?:twoim )?(?:koncie|rachunku)\s+(?:pojawi(?:a)? się|znajdzie się)\s+"
    rf"({PAYOUT_NUMBER})\s*({PAYOUT_CURRENCY})\s+w\s+(?:zaledwie\s+|ciągu\s+)?(\d{{1,2}})\s+dni"
)


def promises_multiple(stake: re.Match, credit: re.Match) -> bool:
    def currency(value: str) -> str:
        return "pln" if value.casefold().startswith("zł") else value.casefold()

    def amount(match: re.Match) -> Decimal:
        return Decimal("".join(match[1].split()).replace(",", "."))

    return (currency(stake[2]) == currency(credit[2])
            and 1 <= int(credit[3]) <= 30 and 0 < amount(stake) * 2 <= amount(credit))


UNIVERSAL_PAYOUT = words(
    r"(?:każdy (?:mieszkaniec|obywatel|polak)(?: Polski)? może|wszyscy mogą)"
    r"\s+(?:teraz\s+)?(?:wypłacać|otrzymywać|odbierać)\s+"
    rf"(?:od\s+{PAYOUT_NUMBER}\s*(?:{PAYOUT_CURRENCY}\s*)?do\s+)?"
    rf"{PAYOUT_NUMBER}\s*{PAYOUT_CURRENCY}\s+"
    r"(?:co (?:tydzień|miesiąc)|tygodniowo|miesięcznie|dziennie)"
)
SIGNUP_DEADLINE = words(
    r"(?:rejestracja|zapisy)\s+(?:zamyka się|kończy się|kończą się|tylko)"
    r"\s+(?:dziś\s+)?(?:o północy|do północy|wieczorem|dzisiaj|dziś)"
)
AUTOPILOT = words(r"na autopilocie|bez twojego udziału|w pełni automatycznie")
PERIODIC_INCOME = words(
    r"(?:(?:stały|pewny|gwarantowany) (?:dochód|zysk)(?: w wysokości)?|"
    r"zacznij zarabiać|zarabiaj|będziesz zarabiać)\s+"
    r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?\s*(?:zł(?:otych)?|pln)\s+"
    r"(?:tygodniowo|dziennie|miesięcznie|co tydzień|co miesiąc|na (?:dzień|tydzień|miesiąc))"
)
ENDORSE = words(r"(?:rząd|ministerstwo|KNF|NBP|prezydent|premier) (?:\w+ ){0,2}(?:uruchomił[ao]?|poleca|rekomenduje|wspiera|patronuje)|(?:aktor|aktorka|piłkarz|prezenter|prezenterka) (?:\w+ ){0,3}(?:poleca|reklamuje|rekomenduje)|pod patronatem (?:rządu|ministerstwa|KNF|NBP)")
REGISTER = words(r"zarejestruj się|załóż konto|wypełnij formularz|(?:zostaw|podaj) (?:swój )?(?:numer|telefon|kontakt)")
NEGATION = re.compile(r"\bnie\s+(?:(?:należy|musisz|trzeba|można|jest|wolno)\s+)?$", re.I)
WARNING = words(r"uważaj na|ostrzegamy przed|przykład oszustwa|oszuści (?:piszą|obiecują|proszą)|nie daj się nabrać")
QUOTED = re.compile(WARNING.pattern + r"[^.!?«„\"]{0,160}[«„\"](?:[^»”\"]{1,3000})[»”\"]", re.I)


@dataclass(frozen=True)
class Signal:
    code: str
    reason: str
    floor: float
    conditions: tuple[re.Pattern, ...]


SIGNALS = (
    Signal("ASSURED_RETURN_SIGNUP", "Reklama przedstawia wysoki krótkoterminowy zwrot jako pewny i nakłania do rejestracji pod presją czasu lub liczby miejsc.", .70, (ASSURED_SHORT_RETURN, REGISTER, DEADLINE)),
    Signal("ALGORITHM_ACCOUNT_CREDIT", "Po wpłacie i uruchomieniu algorytmu reklama obiecuje co najmniej podwojenie tej kwoty na koncie w ciągu 30 dni.", .70, (STAKE, ALGORITHM_REQUEST, ACCOUNT_CREDIT)),
    Signal("AUTOPILOT_INCOME", "Reklama obiecuje określoną kwotę regularnego zarobku bez udziału odbiorcy i zapewnia o pewnym wyniku.", .70, (PERIODIC_INCOME, AUTOPILOT, CERTAINTY)),
    Signal("CRYPTO_FORECAST_DEPOSIT", "Reklama zapowiada konkretny procentowy wzrost kryptowaluty w krótkim terminie i nakłania do wpłaty przed wygaśnięciem oferty.", .70, (CRYPTO_FORECAST, COMMIT_FUNDS, OFFER_EXPIRY)),
    Signal("PUBLIC_PLATFORM_PAYOUT", "Oferta powołuje się na publiczną platformę, obiecuje każdemu regularne wypłaty i wyznacza pilny termin rejestracji.", .70, (PUBLIC_PLATFORM, UNIVERSAL_PAYOUT, SIGNUP_DEADLINE)),
    Signal("EARNINGS_STORY", "Historia szybkiego zarobku promuje rzekomo tajny sposób inwestowania i nakłania do kliknięcia, zanim oferta zniknie.", .70, (EARNINGS_STORY, SECRET_INVESTMENT, EXPIRING_LINK)),
    Signal("FIXED_TRADING_INCOME", "Reklama obiecuje stały, określony kwotowo dochód z handlu w imieniu odbiorcy i wywiera presję na szybką decyzję.", .70, (MANAGED_TRADING, PERIODIC_INCOME, DEADLINE)),
    Signal("WITHDRAWAL_FEE", "Reklama uzależnia wypłatę środków od dodatkowej wpłaty.", .70, (PAY, FEE, RELEASE)),
    Signal("REMOTE_ACCESS", "W kontekście inwestycji odbiorca ma uruchomić zdalny dostęp i przekazać kontrolę nad urządzeniem.", .70, (FINANCE, REMOTE, ACCESS)),
    Signal("RISK_FREE_PAYMENT", "Wezwaniu do wpłaty towarzyszy zapewnienie o braku ryzyka lub pewnym wyniku inwestycji.", .70, (COMMIT_FUNDS, FINANCE, CERTAINTY)),
    Signal("PAYMENT_PRESSURE", "Oferta inwestycyjna łączy wpłatę z presją czasu lub ograniczoną liczbą miejsc.", .40, (FINANCE, PAY, DEADLINE)),
    Signal("ENDORSEMENT_SIGNUP", "Sprawdź deklarowane powiązanie z instytucją lub osobą publiczną. Oferta inwestycyjna zachęca do rejestracji lub podania kontaktu.", .40, (FINANCE, ENDORSE, REGISTER)),
)


def solicitation_signals(text: str) -> tuple[list[ViolatedRule], list[str], float]:
    # A warning is a boundary: do not combine claims from either side of it.
    parts = re.split(r"(?<=[.!?])\s+", QUOTED.sub(" Ostrzegamy przed. ", text))
    recent = []
    found = {}
    quotes = []
    floor = 0.0
    patterns = {condition for signal in SIGNALS for condition in signal.conditions}
    for sentence in parts:
        if WARNING.search(sentence):
            recent.clear()
            continue
        hits = {}
        for pattern in patterns:
            match = next((m for m in pattern.finditer(sentence)
                          if not NEGATION.search(sentence[max(0, m.start()-30):m.start()])), None)
            if match:
                hits[pattern] = match
        recent = (recent + [(sentence, hits)])[-3:]
        combined = set().union(*(matches for _, matches in recent))
        for signal in SIGNALS:
            if signal.code in found or not combined.issuperset(signal.conditions):
                continue
            if signal.code == "ALGORITHM_ACCOUNT_CREDIT":
                evidence = {pattern: match for _, hits in recent for pattern, match in hits.items()}
                if not promises_multiple(evidence[STAKE], evidence[ACCOUNT_CREDIT]):
                    continue
            found[signal.code] = ViolatedRule(
                rule_id=f"M2_{signal.code}", rule_name=signal.reason,
                legal_basis="Wskaźnik analityczny do weryfikacji",
                severity="high" if signal.floor >= .70 else "medium", reason=signal.reason,
            )
            floor = max(floor, signal.floor)
            for passage, matches in recent:
                if matches.keys() & set(signal.conditions) and passage not in quotes:
                    quotes.append(passage)
    return list(found.values()), quotes, floor
