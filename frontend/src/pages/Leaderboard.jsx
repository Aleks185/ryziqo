import { useEffect, useState } from "react";
import { Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { backend } from "@/lib/api";
import { useApp } from "@/lib/store";

const medals = [
  "border-amber-300 bg-amber-50 text-amber-900",
  "border-slate-300 bg-slate-50 text-slate-700",
  "border-orange-200 bg-orange-50 text-orange-900",
];

export default function Leaderboard() {
  const { lang } = useApp();
  const l = (pl, en) => lang === "en" ? en : pl;
  const [ranks, setRanks] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    backend.intel("leaderboard", { signal: controller.signal, timeout: 5000 })
      .then(rows => { if (!controller.signal.aborted) setRanks(rows); })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl space-y-2">
          <h1 className="text-3xl font-bold text-[#0B192C]">{l("Drabinka zgłoszeń", "Report leaderboard")}</h1>
          <p className="text-slate-600">{l("1 punkt = 1 zgłoszenie potwierdzone przez analityka. Zgłoszenia anonimowe nie są wliczane do rankingu.", "Earn one point per report confirmed by an analyst. Anonymous reports are excluded.")}</p>
        </div>
        <Link to="/public" className="rounded-md bg-[#0A1E33] px-4 py-2 text-sm font-semibold text-white focus-ring">{l("Dodaj zgłoszenie", "Submit a report")}</Link>
      </header>

      {!ranks && <p role={error ? "alert" : "status"} className="rounded-lg border border-slate-200 bg-white p-5">
        {error ? l("Nie udało się wczytać drabinki. Spróbuj odświeżyć stronę.", "Could not load the leaderboard. Try refreshing the page.") : l("Wczytywanie drabinki…", "Loading leaderboard…")}
      </p>}

      {ranks?.length === 0 && <div className="rounded-lg border border-slate-200 bg-white p-6 text-center">
        <Trophy className="mx-auto mb-3 size-6 text-slate-500" aria-hidden="true" />
        <p className="font-semibold">{l("Brak potwierdzonych zgłoszeń", "No confirmed reports yet")}</p>
        <p className="mt-1 text-sm text-slate-600">{l("Pierwsze punkty pojawią się po potwierdzeniu zgłoszenia z nickiem.", "The first points will appear after a report with a nickname is confirmed.")}</p>
      </div>}

      {ranks?.length > 0 && <ol className="grid gap-3 sm:grid-cols-3" aria-label={l("Podium", "Podium")}>
        {ranks.slice(0, 3).map(({ nickname, points }, index) => (
          <li key={index} className={`rounded-lg border p-5 ${medals[index]}`}>
            <div className="flex items-center justify-between text-sm font-semibold">
              <span>{index + 1}. {l("miejsce", "place")}</span><Trophy className="size-5" aria-hidden="true" />
            </div>
            <p className="mt-3 break-words text-lg font-bold">{nickname}</p>
            <p className="mt-1 text-sm tabular-nums">{points} {l("pkt", "pts")}</p>
          </li>
        ))}
      </ol>}

      {ranks?.length > 3 && <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100 text-slate-700"><tr>
            {[l("Miejsce", "Rank"), l("Nick", "Nickname"), l("Punkty", "Points")].map(label => <th key={label} scope="col" className="px-2 py-3 sm:px-5">{label}</th>)}
          </tr></thead>
          <tbody>{ranks.slice(3).map(({ nickname, points }, index) => <tr key={index} className="border-t border-slate-200">
            <td className="px-2 py-3 sm:px-5">{index + 4}</td>
            <th scope="row" className="break-all px-2 py-3 font-semibold sm:px-5">{nickname}</th>
            <td className="px-2 py-3 tabular-nums sm:px-5">{points}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  );
}
