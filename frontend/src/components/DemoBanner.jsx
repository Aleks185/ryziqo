import { AlertTriangle, RefreshCw } from "lucide-react";
import { useApp } from "@/lib/store";
import { API_URL } from "@/lib/config";

export const DemoBanner = () => {
  const { mode, demoReason, connect, t } = useApp();
  if (mode === "online") return null;
  return (
    <div data-testid="demo-banner" role="status" className="no-print bg-amber-50 border-b border-amber-300 text-amber-950">
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
        <span className="font-semibold">{t("demo_banner")}</span>
        {demoReason && (
          <span data-testid="demo-banner-reason" className="text-amber-900">
            {t(`demo_reason_${demoReason}`)} <span className="font-mono">({API_URL})</span>
          </span>
        )}
        <button
          type="button"
          data-testid="demo-banner-retry-button"
          onClick={connect}
          disabled={mode === "checking"}
          className="ml-auto inline-flex items-center gap-1.5 border border-amber-400 px-2.5 py-1 rounded-sm font-mono font-bold hover:bg-white hover:text-amber-950 transition-colors focus-ring disabled:opacity-60"
        >
          <RefreshCw className={`h-3 w-3 ${mode === "checking" ? "animate-spin" : ""}`} aria-hidden />
          {t("retry")}
        </button>
      </div>
    </div>
  );
};
