"""Polish monetary offers. Matched passages are evidence for triage."""
import re
from dataclasses import dataclass, field

MONEY = re.compile(
    r"(?<!\w)\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?\s*(?:tys\.?\s*)?(?:zł(?:otych)?|PLN)\b",
    re.I,
)
EARN = re.compile(
    r"\b(?:zarabiaj|zarób|zarobić|zarobisz|zyskasz|zyskaj|osiągnij zysk|"
    r"otrzymuj dochód|zapewnij sobie (?:dodatkowy )?dochód)\b", re.I,
)
TERM = re.compile(
    r"\b(?:(?:w ciągu|już po|po|w|przez)\s+(?:pierwszy[mch]*\s+|jedn\w*\s+|\d+\s+)?"
    r"(?:godzin\w*|dob\w*|dni\w*|dzień|tydzień|tygodni\w*|miesiąc\w*)|"
    r"tygodniowo|dziennie|miesięcznie|jeszcze dziś)\b", re.I,
)
REWARD = re.compile(r"\b(?:zdobądź|odbierz|otrzymaj|zgarnij|dostaniesz|bonus|premi[ęa])\b", re.I)
ACTION = re.compile(
    r"\b(?:(?:za|po)\s+(?:sam[oej]+\s+)?(?:założeni[eu]|otwarci[eu]|aktywacj[ęi])\s+(?:konta|rachunku)|"
    r"po (?:rejestracji|pierwszej wpłacie))\b", re.I,
)
DEPOSIT = re.compile(r"\b(?:wpłać|wpłacić|wpłacając|minimaln\w*\s+depozyt|depozyt początkowy)\b", re.I)
PRESSURE = re.compile(r"\b(?:link zniknie|tylko do północy|(?:zostało|pozostało)\s+(?:tylko\s+)?\d+\s+(?:wolnych\s+)?miejsc)\b", re.I)
GUARANTEE = re.compile(r"(?<!nie )\bgwarantowan\w*\s+(?:dochód|zysk|zwrot)\b", re.I)
WARNING = re.compile(r"\b(?:uważaj na|ostrzegamy przed|ostrzeżenie przed|przykład oszustwa|nie daj się nabrać)\b", re.I)
# A quoted advert in a consumer warning can contain multiple sentences.
QUOTED_WARNING = re.compile(
    WARNING.pattern + r"[^.!?«„\"]{0,160}[«„\"](?:[^»”\"]{1,3000})[»”\"]", re.I,
)


@dataclass
class OfferEvidence:
    floor: float = 0.0
    quotes: list[str] = field(default_factory=list)
    reason: str = ""


def assess_offer(text: str) -> OfferEvidence:
    text = QUOTED_WARNING.sub(" ", text)
    sentences = re.split(r"(?<!tys\.)(?<=[.!?])\s+", text, flags=re.I)
    passages = [s.strip() if not WARNING.search(s) else "" for s in sentences]
    best = OfferEvidence()
    for idx, sentence in enumerate(passages):
        if not MONEY.search(sentence):
            continue
        if ACTION.search(sentence) and REWARD.search(sentence):
            if not best.quotes:
                best = OfferEvidence(quotes=[sentence])
            continue
        verb = EARN.search(sentence)
        if not verb or not MONEY.search(sentence, verb.end()) or not TERM.search(sentence):
            continue
        nearby = passages[max(0, idx - 3):idx + 5]
        deposit = next((s for s in nearby if DEPOSIT.search(s) and MONEY.search(s)), "")
        pressure = next((s for s in nearby if PRESSURE.search(s)), "")
        guarantee = next((s for s in nearby if GUARANTEE.search(s)), "")
        floor = 0.4
        reason = "Reklama obiecuje określoną kwotę zarobku w podanym czasie."
        if deposit and (pressure or guarantee):
            floor = 0.70
            reason += " Łączy obietnicę z wymaganą wpłatą oraz " + (
                "presją czasu lub ograniczoną liczbą miejsc." if pressure else "gwarancją dochodu."
            )
        if floor > best.floor:
            quotes = list(dict.fromkeys(s for s in (sentence, deposit, pressure, guarantee) if s))
            best = OfferEvidence(floor, quotes, reason)
    return best
