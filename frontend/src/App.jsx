import { useEffect, useState } from "react";
import {
  Activity,
  CircleOff,
  Cpu,
  RefreshCw,
} from "lucide-react";

import RelayCard from "./components/RelayCard";
import { RELAYS } from "./config/relays";
import { getBackendHealth } from "./services/relayApi";
import WateringPanel from "./components/WateringPanel";
import AutomationsPanel from "./components/AutomationsPanel";

export default function App() {
  const [backendStatus, setBackendStatus] = useState("checking");

  async function checkBackend() {
    setBackendStatus("checking");

    try {
      await getBackendHealth();
      setBackendStatus("online");
    } catch {
      setBackendStatus("offline");
    }
  }

  useEffect(() => {
    checkBackend();
  }, []);

  return (
    <main className="min-h-screen bg-slate-100 text-slate-950">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:py-12">
        <header className="overflow-hidden rounded-3xl bg-slate-950 px-6 py-8 text-white shadow-2xl sm:px-10">
          <div className="flex flex-col justify-between gap-8 lg:flex-row lg:items-end">
            <div>
              <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-white/10">
                <Cpu size={25} />
              </div>

              <p className="text-sm font-medium uppercase tracking-[0.22em] text-slate-400">
                Raspberry Pi Home Automation
              </p>

              <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
                Terrace Control
              </h1>

              <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Direct control of the six physical relay channels. Commands
                represent relay-coil ON and OFF states; appliance state is not
                tracked.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div
                className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold ${
                  backendStatus === "online"
                    ? "bg-emerald-400/15 text-emerald-300"
                    : backendStatus === "offline"
                      ? "bg-red-400/15 text-red-300"
                      : "bg-white/10 text-slate-300"
                }`}
              >
                {backendStatus === "online" ? (
                  <Activity size={17} />
                ) : (
                  <CircleOff size={17} />
                )}

                Backend {backendStatus}
              </div>

              <button
                type="button"
                onClick={checkBackend}
                className="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 transition hover:bg-white/20"
                aria-label="Check backend"
              >
                <RefreshCw
                  size={17}
                  className={
                    backendStatus === "checking"
                      ? "animate-spin"
                      : ""
                  }
                />
              </button>
            </div>
          </div>
        </header>

        <WateringPanel />
        <AutomationsPanel />
        <section className="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {RELAYS.map((relay) => (
            <RelayCard key={relay.key} relay={relay} />
          ))}
        </section>

        <footer className="mt-8 text-center text-xs text-slate-500">
          Relay state is intentionally not persisted or inferred.
        </footer>
      </div>
    </main>
  );
}