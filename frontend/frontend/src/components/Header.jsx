import { NavLink } from "react-router-dom";
import { Logo } from "./Logo";
import { useApp } from "@/lib/store";

const LINKS = [
  ["/", "nav_dashboard", "nav-dashboard"],
  ["/analyze", "nav_analyze", "nav-analyze"],
  ["/calibration", "nav_calibration", "nav-calibration"],
  ["/log", "nav_log", "nav-log"],
];

const ConnectionPill = () => {
  const { mode, wsStatus, t } = useApp();
  const dot = mode === "online" ? (wsStatus === "connected" ? "bg-emerald-400" : "bg-amber-400") : mode === "demo" ? "bg-red-500" : "bg-slate-400";
  return (
    <div data-testid="nav-connection-status" className="flex items-center gap-2 border border-[#2E5077] rounded-sm px-2.5 py-1 font-mono text-[11px] tracking-wide">
      <span className={`h-2 w-2 rounded-full ${dot} ${mode === "online" && wsStatus === "connected" ? "animate-pulse" : ""}`} />
      <span className="font-bold">{t(`conn_${mode}`)}</span>
      <span className="hidden md:inline text-slate-400">· {t(`ws_${wsStatus}`)}</span>
    </div>
  );
};

export const Header = () => {
  const { lang, setLang, t } = useApp();
  return (
    <header className="no-print sticky top-0 z-40 bg-[#0B192C] text-white border-b border-[#1E3E62]">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 flex flex-wrap items-center gap-x-6 gap-y-2 py-2.5">
        <NavLink to="/" data-testid="nav-logo" className="flex items-center gap-3 focus-ring">
          <Logo />
          <div className="leading-tight">
            <div className="font-bold tracking-[0.14em] text-sm">INVESTWATCH</div>
            <div className="text-[11px] text-slate-400 hidden sm:block">{t("app_sub")}</div>
          </div>
        </NavLink>
        <nav className="flex flex-wrap gap-1 order-3 lg:order-none w-full lg:w-auto">
          {LINKS.map(([to, key, id]) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              data-testid={id}
              className={({ isActive }) =>
                `px-3 py-1.5 text-sm rounded-sm transition-colors focus-ring ${isActive ? "bg-white text-[#0B192C] font-semibold" : "text-slate-300 hover:bg-[#1E3E62] hover:text-white"}`
              }
            >
              {t(key)}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <ConnectionPill />
          <div className="flex border border-[#2E5077] rounded-sm overflow-hidden" role="group" aria-label="Language">
            {["pl", "en"].map((l) => (
              <button
                key={l}
                type="button"
                data-testid={`nav-lang-${l}`}
                onClick={() => setLang(l)}
                aria-pressed={lang === l}
                className={`px-2.5 py-1 text-xs font-mono font-bold uppercase focus-ring transition-colors ${lang === l ? "bg-white text-[#0B192C]" : "text-slate-300 hover:bg-[#1E3E62]"}`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  );
};
