import { useEffect, useState } from "react";
import {
  CircleStop,
  LoaderCircle,
  Play,
  RefreshCw,
  Sprout,
} from "lucide-react";

import {
  getWateringStatus,
  startWatering,
  stopWatering,
} from "../services/relayApi";

export default function WateringPanel() {
  const [status, setStatus] = useState(null);
  const [pendingCommand, setPendingCommand] = useState(null);
  const [error, setError] = useState(null);

  async function refreshStatus() {
    try {
      setStatus(await getWateringStatus());
      setError(null);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function runCommand(command) {
    setPendingCommand(command);
    setError(null);

    try {
      if (command === "start") {
        await startWatering();
      } else {
        await stopWatering();
      }

      await refreshStatus();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPendingCommand(null);
    }
  }

  useEffect(() => {
    refreshStatus();

    const interval = window.setInterval(refreshStatus, 3000);

    return () => window.clearInterval(interval);
  }, []);

  return (
    <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-600 text-white">
            <Sprout size={24} />
          </div>

          <div>
            <h2 className="text-xl font-semibold text-slate-950">
              Panel Cleaning and Plant Watering
            </h2>

            <p className="mt-1 text-sm text-slate-600">
              Runs the complete timed sprinkler and plant-watering sequence.
            </p>

            <p className="mt-2 text-xs font-medium text-amber-700">
              Do not start until the main motorised valve is repaired.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div
            className={`rounded-full px-4 py-2 text-sm font-semibold ${
              status?.running
                ? "bg-emerald-100 text-emerald-700"
                : "bg-slate-100 text-slate-600"
            }`}
          >
            {status?.running
              ? "Running"
              : `Idle · ${status?.last_result || "unknown"}`}
          </div>

          <button
            type="button"
            onClick={refreshStatus}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50"
            aria-label="Refresh watering status"
          >
            <RefreshCw size={17} />
          </button>

          <button
            type="button"
            disabled={pendingCommand !== null || status?.running}
            onClick={() => runCommand("start")}
            className="flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingCommand === "start" ? (
              <LoaderCircle size={18} className="animate-spin" />
            ) : (
              <Play size={18} />
            )}
            Start
          </button>

          <button
            type="button"
            disabled={pendingCommand !== null || !status?.running}
            onClick={() => runCommand("stop")}
            className="flex items-center gap-2 rounded-xl bg-red-600 px-4 py-3 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingCommand === "stop" ? (
              <LoaderCircle size={18} className="animate-spin" />
            ) : (
              <CircleStop size={18} />
            )}
            Safe Stop
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
    </section>
  );
}