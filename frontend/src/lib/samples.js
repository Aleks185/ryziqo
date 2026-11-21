// Fictional sample ads (not real UKNF materials). ground_truth = reference label for calibration.
export const SAMPLES = [
  {
    id: "S1",
    title: { pl: "Finfluencer kryptowalutowy z kodem polecającym", en: "Crypto finfluencer with referral code" },
    expected: ["M1", "M2"],
    ground_truth: true,
    content:
      "Hej! Od 3 miesięcy zarabiam 40% miesięcznie na bocie CryptoMax. Zero ryzyka, gwarantowany zysk — sprawdziłam to na własnym portfelu. Z moim kodem polecającym KRYPTO50 dostaniesz bonus na start, link w bio! @kasia.inwestuje",
  },
  {
    id: "S2",
    title: { pl: "Reklama CFD bez ostrzeżenia o ryzyku", en: "CFD ad without risk warning" },
    expected: ["M2"],
    ground_truth: true,
    content:
      "XTradePro — handluj kontraktami CFD na złoto i ropę z dźwignią 1:500! Minimalny depozyt to tylko 250 zł. Otwórz konto w 5 minut i zacznij zarabiać już dziś. Szczegóły w regulaminie.",
  },
  {
    id: "S3",
    title: { pl: "Płatna grupa sygnałowa na Telegramie", en: "Paid Telegram signal group" },
    expected: ["M3"],
    ground_truth: true,
    content:
      "Dołącz do grupy VIP na Telegramie — tylko 199 zł miesięcznie. Dzisiejszy sygnał: kupuj BTC, cena wejścia 61 500 USD, take profit 64 000, stop loss 60 200. Kopiuj moje transakcje, a wyniki przyjdą same.",
  },
  {
    id: "S4",
    title: { pl: "Reklama CFD z poprawnym ostrzeżeniem", en: "CFD ad with correct warning" },
    expected: [],
    ground_truth: false,
    content:
      "Kontrakty CFD są złożonymi instrumentami i wiążą się z wysokim ryzykiem szybkiej utraty środków pieniężnych z powodu dźwigni finansowej. 74% rachunków inwestorów detalicznych traci pieniądze w wyniku handlu kontraktami CFD u tego dostawcy. Zastanów się, czy rozumiesz, jak działają kontrakty CFD.",
  },
  {
    id: "S5",
    title: { pl: "Materiał edukacyjny o dywersyfikacji", en: "Educational post on diversification" },
    expected: [],
    ground_truth: false,
    content:
      "Materiał edukacyjny: czym jest dywersyfikacja portfela? To rozłożenie środków na różne klasy aktywów. Pamiętaj, że inwestowanie wiąże się z ryzykiem utraty części lub całości kapitału. Ten wpis nie jest rekomendacją inwestycyjną.",
  },
  {
    id: "S6",
    title: { pl: "Ukryte zarządzanie kapitałem i sygnały forex", en: "Hidden asset management and forex signals" },
    expected: ["M1", "M3"],
    ground_truth: true,
    content:
      "Współpraca z FxSignals Capital. Przekaż mi 5000 zł, zarządzam kapitałem klientów — średnio 15% tygodniowo. Sprzedaj EUR/USD teraz, wchodźcie przed 14:00! Kod rabatowy FX20 znajdziesz w opisie.",
  },
];
