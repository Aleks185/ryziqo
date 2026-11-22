import { useEffect, useState } from "react";
import { Activity, ClipboardList, FileSearch, Gauge, LayoutDashboard, Menu, Network, Radar, ScanSearch, Share2, ShieldAlert, Trophy } from "lucide-react";
import { Link, NavLink, matchPath, useLocation } from "react-router-dom";
import { Logo } from "./Logo";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "./ui/sheet";
import { useApp } from "@/lib/store";

const LINKS = [
  ["/", "nav_dashboard", "nav-dashboard", LayoutDashboard],
  ["/analyze", "nav_analyze", "nav-analyze", FileSearch],
  ["/crawler", ["Crawler", "Crawler"], "nav-crawler", Radar],
  ["/reports", "intel_reports", "nav-reports", ClipboardList],
  ["/campaigns", "intel_campaigns", "nav-campaigns", Network],
  ["/leaderboard", ["Drabinka (Leaderboard)", "Leaderboard"], "nav-leaderboard", Trophy],
  ["/graph", "nav_graph", "nav-graph", Share2],
  ["/diagnostics", "intel_diag", "nav-diagnostics", Activity],
  ["/calibration", "nav_calibration", "nav-calibration", Gauge],
  ["/log", "nav_log", "nav-log", ScanSearch],
];

function usePublicView() {
  const { pathname } = useLocation();
  return Boolean(matchPath("/public", pathname) || matchPath("/leaderboard", pathname));
}

function ConnectionPill() {
  const { mode, backendMode, wsStatus, t } = useApp();
  const connected = mode === "online" && wsStatus === "connected";
  const fallback = mode === "online" && backendMode === "demo_fallback";
  const dot = connected && !fallback ? "bg-emerald-400" : mode === "checking" ? "bg-slate-400" : "bg-amber-400";

  return (
    <div data-testid="nav-connection-status" className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] font-mono">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <span className="font-bold">{t(`conn_${mode}`)}</span>
      {fallback && <span className="font-bold text-amber-300">{t("conn_fallback")}</span>}
      <span className="text-slate-400">{t(`ws_${wsStatus}`)}</span>
    </div>
  );
}

function NavigationContent({ onNavigate }) {
  const { lang, t } = useApp();
  const menuLabel = lang === "pl" ? "Nawigacja główna" : "Main navigation";

  return (
    <nav aria-label={menuLabel} className="px-3 py-4">
      <ul className="space-y-1">
        {LINKS.map(([to, label, id, Icon]) => (
          <li key={to}>
            <NavLink
              to={to}
              end={to === "/"}
              onClick={onNavigate}
              data-testid={id}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors focus-ring ${isActive ? "bg-white font-semibold text-[#0B192C]" : "text-slate-200 hover:bg-[#1E3E62] hover:text-white"}`
              }
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {Array.isArray(label) ? label[lang === "en" ? 1 : 0] : t(label)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function HeaderControls({ publicView }) {
  const { lang, setLang, t } = useApp();

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 px-3 pb-2 sm:px-4 lg:min-h-[66px] lg:py-2">
      <nav aria-label={lang === "pl" ? "Tryb aplikacji" : "Application mode"} className="inline-flex max-w-full rounded-md border border-[#2E5077]">
        {[
          { to: "/", label: "analyst", active: !publicView, Icon: LayoutDashboard },
          { to: "/public", label: "citizen", active: publicView, Icon: ShieldAlert },
        ].map(({ to, label, active, Icon }) => (
          <Link
            key={to}
            to={to}
            aria-current={active ? "true" : undefined}
            className={`flex items-center gap-1.5 rounded-sm px-2 py-2 text-left text-xs font-semibold transition-colors focus-ring sm:px-3 sm:text-sm ${active ? "bg-white text-[#0B192C]" : "text-white hover:bg-[#1E3E62]"}`}
          >
            <Icon className="hidden h-4 w-4 shrink-0 sm:block" aria-hidden="true" />
            {t(label)}
          </Link>
        ))}
      </nav>
      {!publicView && <ConnectionPill />}
      <div className="inline-flex overflow-hidden rounded-md border border-[#2E5077]" role="group" aria-label={lang === "pl" ? "Język" : "Language"}>
        {["pl", "en"].map((language) => (
          <button
            key={language}
            type="button"
            data-testid={`nav-lang-${language}`}
            onClick={() => setLang(language)}
            aria-pressed={lang === language}
            className={`px-3 py-1.5 font-mono text-xs font-bold uppercase transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-amber-500 ${lang === language ? "bg-white text-[#0B192C]" : "text-slate-200 hover:bg-[#1E3E62]"}`}
          >
            {language}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Sidebar() {
  const publicView = usePublicView();
  if (publicView) return null;

  return (
    <aside className="no-print sticky top-0 hidden h-dvh w-64 shrink-0 flex-col self-start overflow-y-auto border-r border-[#2E5077] bg-[#0A1E33] text-white lg:flex">
      <Link to="/" data-testid="nav-logo" className="flex min-w-0 justify-center border-b border-[#2E5077] py-3 focus-ring">
        <Logo wide />
      </Link>
      <NavigationContent />
    </aside>
  );
}

function MobileNavigation() {
  const [open, setOpen] = useState(false);
  const { lang } = useApp();
  const { key } = useLocation();
  const menuLabel = lang === "pl" ? "Nawigacja główna" : "Main navigation";

  useEffect(() => setOpen(false), [key]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    const closeOnDesktop = (event) => {
      if (event.matches) setOpen(false);
    };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  return (
    <div className="flex h-[66px] items-center gap-1 px-3 py-2 lg:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <button type="button" aria-label={menuLabel} className="rounded-md p-2 transition-colors hover:bg-[#1E3E62] focus-ring">
            <Menu className="h-6 w-6" aria-hidden="true" />
          </button>
        </SheetTrigger>
        <SheetContent side="left" aria-describedby={undefined} className="no-print flex w-[min(18rem,100%)] flex-col gap-0 overflow-y-auto border-[#2E5077] bg-[#0A1E33] p-0 pt-10 text-white">
          <SheetTitle className="sr-only">{menuLabel}</SheetTitle>
          <div className="flex justify-end border-b border-[#2E5077] px-3 pb-2">
            <Link to="/" data-testid="drawer-nav-logo" onClick={() => setOpen(false)} className="rounded-sm focus-ring">
              <Logo wide />
            </Link>
          </div>
          <NavigationContent onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      {!open && (
        <Link to="/" data-testid="mobile-nav-logo" className="rounded-sm focus-ring">
          <Logo wide />
        </Link>
      )}
    </div>
  );
}

export function Header() {
  const publicView = usePublicView();

  return (
    <header className="no-print sticky top-0 z-40 flex flex-wrap items-center justify-end border-b border-[#2E5077] bg-[#0A1E33] text-white">
      {publicView ? (
        <Link to="/" className="mr-auto rounded-sm px-3 py-2 focus-ring">
          <Logo wide />
        </Link>
      ) : (
        <div className="mr-auto lg:hidden"><MobileNavigation /></div>
      )}
      <HeaderControls publicView={publicView} />
    </header>
  );
}
