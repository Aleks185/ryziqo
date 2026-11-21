import "@/App.css";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppProvider } from "@/lib/store";
import { Header } from "@/components/Header";
import { DemoBanner } from "@/components/DemoBanner";
import Dashboard from "@/pages/Dashboard";
import Analyze from "@/pages/Analyze";
import IncidentDetail from "@/pages/IncidentDetail";
import Calibration from "@/pages/Calibration";
import LogPage from "@/pages/LogPage";

import Citizen from "@/pages/Citizen";

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <div className="min-h-screen bg-[#F8FAFC] text-slate-800">
          <Header />
          <DemoBanner />
          <main className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/public" element={<Citizen />} />
              <Route path="/analyze" element={<Analyze />} />
              <Route path="/incidents/:id" element={<IncidentDetail />} />
              <Route path="/calibration" element={<Calibration />} />
              <Route path="/log" element={<LogPage />} />
            </Routes>
          </main>
        </div>
        <Toaster position="bottom-right" theme="light" richColors closeButton />
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
