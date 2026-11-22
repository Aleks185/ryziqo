import { Component } from "react";
import { useLocation } from "react-router-dom";
import { useApp } from "@/lib/store";

class Boundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    const { failed } = this.state;
    const { t, children } = this.props;
    if (!failed) return children;
    return (
      <div role="alert" data-testid="page-error" className="bg-white border border-[#CBD5E1] border-l-4 border-l-[#DC2626] rounded-sm p-6 max-w-xl">
        <h2 className="text-lg font-bold text-[#0B192C]">{t("page_error_title")}</h2>
        <p className="mt-2 text-sm text-slate-600">{t("page_error_body")}</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-4 px-3 py-2 text-sm font-semibold text-white bg-[#0B192C] rounded-sm focus-ring">
          {t("page_error_reload")}
        </button>
      </div>
    );
  }
}

// Błąd renderowania jednej strony nie wywraca całego panelu; zmiana adresu resetuje stan.
export function PageErrorBoundary({ children }) {
  const { pathname } = useLocation();
  const { t } = useApp();
  return (
    <Boundary key={pathname} t={t}>
      {children}
    </Boundary>
  );
}
