import { useState } from "react";
import {
  CheckCircle2,
  LoaderCircle,
  Power,
  PowerOff,
  TriangleAlert,
} from "lucide-react";

import { sendRelayCommand } from "../services/relayApi";

export default function RelayCard({ relay }) {
  const [pendingCommand, setPendingCommand] = useState(null);
  const [result, setResult] = useState(null);

  const Icon = relay.icon;

  async function executeCommand(command) {
    setPendingCommand(command);
    setResult(null);

    try {
      await sendRelayCommand(relay.key, command);

      setResult({
        type: "success",
        text: `${relay.channel} received relay ${command.toUpperCase()}.`,
      });
    } catch (error) {
      setResult({
        type: "error",
        text: error.message,
      });
    } finally {
      setPendingCommand(null);
    }
  }

  return (
    <article className="flex min-h-72 flex-col rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-xl">
      <div className="flex items-start justify-between gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-950 text-white">
          <Icon size={24} strokeWidth={1.8} />
        </div>

        <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {relay.channel} · GPIO {relay.gpio}
        </div>
      </div>

      <div className="mt-5">
        <h2 className="text-xl font-semibold text-slate-950">
          {relay.name}
        </h2>

        <p className="mt-2 text-sm leading-6 text-slate-600">
          {relay.description}
        </p>
      </div>

      <div className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500">
        {relay.wiringNote}
      </div>

      <div className="mt-auto grid grid-cols-2 gap-3 pt-6">
        <button
          type="button"
          disabled={pendingCommand !== null}
          onClick={() => executeCommand("on")}
          className="flex items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pendingCommand === "on" ? (
            <LoaderCircle size={18} className="animate-spin" />
          ) : (
            <Power size={18} />
          )}
          Relay ON
        </button>

        <button
          type="button"
          disabled={pendingCommand !== null}
          onClick={() => executeCommand("off")}
          className="flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pendingCommand === "off" ? (
            <LoaderCircle size={18} className="animate-spin" />
          ) : (
            <PowerOff size={18} />
          )}
          Relay OFF
        </button>
      </div>

      {result && (
        <div
          className={`mt-4 flex items-start gap-2 rounded-xl px-3 py-2 text-xs ${
            result.type === "success"
              ? "bg-emerald-50 text-emerald-700"
              : "bg-red-50 text-red-700"
          }`}
        >
          {result.type === "success" ? (
            <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          ) : (
            <TriangleAlert size={16} className="mt-0.5 shrink-0" />
          )}
          <span>{result.text}</span>
        </div>
      )}
    </article>
  );
}