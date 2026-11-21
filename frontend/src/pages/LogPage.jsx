import { useApp } from "@/lib/store";
import { LiveLog } from "@/components/LiveLog";

export default function LogPage() {
  const { t } = useApp();
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]">{t("log_title")}</h1>
        <p className="text-sm text-slate-600 mt-1">{t("log_lead")}</p>
      </div>
      <LiveLog full />
    </div>
  );
}
