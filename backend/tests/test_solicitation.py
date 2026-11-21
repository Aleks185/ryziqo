import pytest

from app.ai.solicitation import solicitation_signals


@pytest.mark.parametrize(("code", "offer", "control"), [
    ("WITHDRAWAL_FEE", "Przelej 600 zł podatku, aby odblokować wypłatę.", "Prowizję 5 zł potrącimy z wypłacanej kwoty."),
    ("REMOTE_ACCESS", "Aby odebrać zysk, zainstaluj AnyDesk i podaj konsultantowi kod połączenia.", "Przy inwestycji nigdy nie instaluj AnyDesk i nie podawaj kodu połączenia."),
    ("RISK_FREE_PAYMENT", "Zarób swój pierwszy milion w 7 dni dzięki nowej luce w algorytmach bankowych! Wpłać tylko 900 zł i odbierz gwarantowane 45 000 zł już w przyszły piątek – zero ryzyka, 100% skuteczności.", "Wpłać 900 zł. Nie gwarantujemy zysku. Inwestycja wiąże się z ryzykiem utraty kapitału."),
    ("PAYMENT_PRESSURE", "Zostało 17 wolnych miejsc. Wpłać depozyt inwestycyjny do północy.", "Zostało 17 wolnych miejsc. Wpłać zaliczkę na webinar do północy."),
    ("ENDORSEMENT_SIGNUP", "Rząd uruchomił program inwestycyjny. Zostaw numer, doradca oddzwoni.", "Rząd uruchomił program inwestycyjny. Pełny opis opublikowano w komunikacie prasowym."),
])
def test_solicitation(code, offer, control):
    rules, quotes, floor = solicitation_signals(offer)
    assert [rule.rule_id for rule in rules] == [f"M2_{code}"]
    assert quotes and all(quote in offer for quote in quotes)
    assert floor == (.40 if code in {"PAYMENT_PRESSURE", "ENDORSEMENT_SIGNUP"} else .70)
    assert solicitation_signals(control) == ([], [], 0)


def test_negated_guarantee_and_quoted_ad():
    assert not solicitation_signals("Wpłać 900 zł. Nie gwarantujemy zysku z inwestycji.")[0]
    assert not solicitation_signals("Uważaj na reklamy: «Wpłać depozyt. Gwarantujemy zysk!»")[0]
    assert solicitation_signals("Wpłać 900 zł. Gwarantujemy zysk.")[2] == .70


def test_fixed_trading_income_with_scarcity():
    ad = "PILNE! Rząd ukrywa ten program przed zwykłymi obywatelami! Nasza sztuczna inteligencja handluje za Ciebie 24/7, generując stały dochód 15 000 zł tygodniowo bez żadnej wiedzy o giełdzie. Zostały tylko 3 wolne miejsca!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [rule.rule_id for rule in rules] == ["M2_FIXED_TRADING_INCOME"]
    assert floor == .70
    assert any("15 000 zł tygodniowo" in quote for quote in quotes)
    assert any("3 wolne miejsca" in quote for quote in quotes)


@pytest.mark.parametrize("control", [
    "Praca na etacie. Stały dochód 15 000 zł miesięcznie. Zostały tylko 3 wolne miejsca!",
    "Warsztaty o sztucznej inteligencji. Zostały tylko 3 wolne miejsca!",
    "Algorytm handluje za Ciebie. Wyniki są zmienne. Pozostały 2 wolne miejsca.",
    "Uważaj na reklamy: «Bot handluje za Ciebie. Stały dochód 15 000 zł tygodniowo. Zostały tylko 3 miejsca!»",
])
def test_fixed_trading_income_controls(control):
    assert solicitation_signals(control) == ([], [], 0)


def test_earnings_story():
    story = "Jak zwykły magazynier z Poznania zarobił 250 000 zł w dwa tygodnie na jednym kliknięciu? Odkryj tajny system inwestycyjny, którego banki panicznie próbują zakazać. Kliknij, zanim strona zniknie!"
    rules, quotes, floor = solicitation_signals(story)
    assert [rule.rule_id for rule in rules] == ["M2_EARNINGS_STORY"]
    assert floor == .70
    assert len(quotes) == 3 and all(q in story for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + story + "»")[0]


@pytest.mark.parametrize("text", [
    "Projektantka zarobiła 250 000 zł w dwa tygodnie ze sprzedaży licencji.",
    "Odkryj tajny system inwestycyjny. Kliknij, zanim strona zniknie!",
    "Student zarobił 50 000 zł w tydzień. Kliknij, zanim strona zniknie!",
    "Student zarobił 50 000 zł w tydzień. Odkryj tajny system inwestycyjny.",
])
def test_earnings_story_requires_all_three_signals(text):
    assert not solicitation_signals(text)[0]


def test_guaranteed_return_with_investment_amount():
    ad = "Gwarantowany zysk 500% w 48 godzin! Nie musisz pracować na etacie, gdy nasz bot kwantowy pomnaża Twoje oszczędności z pewnością 99,8%. Zainwestuj minimalną kwotę 850 zł i ciesz się wolnością finansową już dziś!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [rule.rule_id for rule in rules] == ["M2_RISK_FREE_PAYMENT"]
    assert floor == .70
    assert any("500% w 48 godzin" in q for q in quotes)
    assert any("850 zł" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("text", [
    "Historyczny zysk wyniósł 500% w 48 godzin. Zainwestuj 850 zł.",
    "Zainwestuj minimalną kwotę 850 zł. Nie gwarantujemy zysku.",
    "Bot osiągnął dokładność 99,8%. Zainwestuj 850 zł.",
    "Zainwestuj czas w kurs. Przykładowa strategia omawia gwarantowany zysk.",
])
def test_investment_amount_requires_an_asserted_guarantee(text):
    assert not solicitation_signals(text)[0]


def test_public_platform_recurring_payout():
    ad = "UWAGA POLACY! Otworzyliśmy darmowy dostęp do narodowej platformy surowcowej. Każdy mieszkaniec Polski może teraz wypłacać od 8 000 do 30 000 zł co tydzień bezpośrednio na swoje konto bankowe. Rejestracja zamyka się o północy!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [rule.rule_id for rule in rules] == ["M2_PUBLIC_PLATFORM_PAYOUT"]
    assert floor == .70
    assert len(quotes) == 3 and all(quote in ad for quote in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("text", [
    "Każdy mieszkaniec Polski może wypłacać od 8 000 do 30 000 zł co tydzień z własnego konta. Limit dotyczy bankomatów.",
    "Darmowy dostęp do narodowej platformy surowcowej. Rejestracja zamyka się o północy.",
    "Każdy obywatel może otrzymywać 200 PLN miesięcznie. Zapisy kończą się dziś.",
])
def test_payout_requires_platform_promise_and_deadline(text):
    assert not solicitation_signals(text)[0]


def test_promised_gain_and_starting_amount():
    ad = "Zostań milionerem przed końcem miesiąca bez wychodzenia z domu! Nasz automatyczny system kopiowania transakcji miliarderów daje Ci 100% gwarancji zysku i pełną ochronę kapitału. Zacznij od 1000 zł!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [r.rule_id for r in rules] == ["M2_RISK_FREE_PAYMENT"]
    assert floor == .70
    assert any("100% gwarancji zysku" in q for q in quotes)
    assert any("Zacznij od 1000 zł" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("control", [
    "Zacznij od 1000 zł. Produkt zapewnia pełną ochronę kapitału.",
    "Zacznij od 1000 zł. System nie daje Ci 100% gwarancji zysku.",
    "Zacznij od bezpłatnego poradnika. Autor obiecuje gwarantowany zysk.",
])
def test_starting_amount_controls(control):
    assert not solicitation_signals(control)[0]


def test_crypto_forecast_with_payment_and_expiry():
    ad = "Szokujące odkrycie na rynku krypto! Ten nieznany token wzrośnie o 12 000% w najbliższy weekend. Zainwestuj 500 zł teraz i wypłać pół miliona w poniedziałek rano – oferta ważna tylko przez najbliższą godzinę!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [r.rule_id for r in rules] == ["M2_CRYPTO_FORECAST_DEPOSIT"]
    assert floor == .70
    assert any("12 000%" in q for q in quotes)
    assert any("Zainwestuj 500 zł" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("control", [
    "Token wzrósł o 12 000% w weekend. Zainwestuj 500 zł. Oferta ważna tylko przez godzinę.",
    "Token wzrośnie o 12 000% w najbliższy weekend. Raport opublikujemy jutro.",
    "Token nie wzrośnie o 12 000% w weekend. Zainwestuj 500 zł. Oferta ważna tylko przez godzinę.",
    "Token wzrośnie o 12 000% w weekend. Zainwestuj 500 zł po zapoznaniu się z ryzykiem.",
])
def test_crypto_forecast_controls(control):
    assert not solicitation_signals(control)[0]


def test_guaranteed_autopilot_income():
    ad = "Przestań spłacać kredyty, zacznij zarabiać 3500 zł dziennie na autopilocie! Dołącz do zamkniętej grupy VIP i odbierz swój gwarantowany dochód pasywny z rządową gwarancją zwrotu. Kliknij „Dowiedz się więcej”!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [r.rule_id for r in rules] == ["M2_AUTOPILOT_INCOME"]
    assert floor == .70
    assert any("3500 zł dziennie na autopilocie" in q for q in quotes)
    assert any("gwarantowany dochód pasywny" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("control", [
    "Zacznij zarabiać 3500 zł miesięcznie na umowie o pracę. Pracodawca oferuje gwarantowany dochód.",
    "Zarabiaj 3500 zł dziennie na autopilocie. Nie gwarantujemy zysku.",
    "Dołącz do grupy VIP. System działa na autopilocie.",
])
def test_autopilot_income_controls(control):
    assert not solicitation_signals(control)[0]


def test_algorithm_promises_large_account_credit():
    ad = "Banki nienawidzą tego jednego prostego triku! Wpłać 950 PLN, włącz algorytm i patrz, jak na Twoim koncie pojawia się 18 000 PLN w zaledwie 5 dni. Zero podatku, zero prowizji, czysty zysk!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [r.rule_id for r in rules] == ["M2_ALGORITHM_ACCOUNT_CREDIT"]
    assert floor == .70
    assert any("950 PLN" in q and "18 000 PLN" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("text", [
    "Wpłać 950 PLN. Na Twoim koncie pojawi się 950 PLN w 5 dni.",
    "Wpłać 950 PLN. Włącz algorytm. Na koncie pojawi się 950 zł w 5 dni.",
    "Wpłać 950 EUR. Uruchom algorytm. Na koncie pojawi się 2 500 PLN w 5 dni.",
    "Zero podatku, zero prowizji. Wpłać 950 PLN.",
])
def test_account_credit_controls(text):
    assert not solicitation_signals(text)[0]


def test_assured_short_return_and_urgent_signup():
    ad = "Ostatnia szansa na dołączenie do programu inwestycyjnego największych polskich spółek energetycznych! Pewny zwrot 300% w tydzień dla każdego obywatela po 18. roku życia. Zarejestruj się teraz, zostało 6 miejsc!"
    rules, quotes, floor = solicitation_signals(ad)
    assert [r.rule_id for r in rules] == ["M2_ASSURED_RETURN_SIGNUP"]
    assert floor == .70
    assert any("300% w tydzień" in q for q in quotes)
    assert any("zostało 6 miejsc" in q for q in quotes)
    assert not solicitation_signals("Uważaj na reklamy: «" + ad + "»")[0]


@pytest.mark.parametrize("control", [
    "Historyczny zwrot 300% w tydzień. Zarejestruj się teraz, zostało 6 miejsc.",
    "Pewny zwrot 3% w skali roku. Zarejestruj się teraz, zostało 6 miejsc.",
    "Webinar o inwestowaniu w energetykę. Zarejestruj się teraz, zostało 6 miejsc.",
    "Pewny zwrot 300% w tydzień. Zarejestruj się w dogodnym terminie.",
])
def test_assured_return_signup_controls(control):
    assert not solicitation_signals(control)[0]
