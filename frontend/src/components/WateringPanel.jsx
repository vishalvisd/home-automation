import { useEffect, useState } from "react";
import {
  CircleStop,
  LoaderCircle,
  Play,
  Save,
  Sprout,
} from "lucide-react";

import {
  getWateringSettings,
  getWateringStatus,
  saveWateringSettings,
  startWatering,
  stopWatering,
} from "../services/relayApi";


const NUMBER_FIELDS = [
  ["frequency_days", "Run every", "days"],
  [
    "main_valve_open_delay_seconds",
    "Main valve open delay",
    "seconds",
  ],
  [
    "main_valve_close_delay_seconds",
    "Main valve close delay",
    "seconds",
  ],
  [
    "plant_valve_open_delay_seconds",
    "Plant valve open delay",
    "seconds",
  ],
  [
    "plant_valve_close_delay_seconds",
    "Plant valve close delay",
    "seconds",
  ],
  [
    "panel_sprinkler_seconds",
    "Panel cleaning duration",
    "seconds",
  ],
  [
    "plant_watering_seconds",
    "Plant watering duration",
    "seconds",
  ],
  [
    "wait_after_pump_stop_seconds",
    "Wait after pump stop",
    "seconds",
  ],
  [
    "water_settling_seconds",
    "Water settling delay",
    "seconds",
  ],
];


export default function WateringPanel() {
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function refreshStatus() {
    try {
      setStatus(await getWateringStatus());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function loadSettings() {
    try {
      setSettings(await getWateringSettings());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveSettings() {
    setPending("save");
    setError(null);
    setMessage(null);

    try {
      const saved = await saveWateringSettings(settings);
      setSettings(saved);
      setMessage("Settings saved.");
      await refreshStatus();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  async function runCommand(command) {
    setPending(command);
    setError(null);
    setMessage(null);

    try {
      if (command === "start") {
        await startWatering();
        setMessage("Watering started.");
      } else {
        await stopWatering();
        setMessage("Safe stop requested.");
      }

      await refreshStatus();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  function updateSetting(key, value) {
    setSettings((current) => ({
      ...current,
      [key]: value,
    }));
  }

  useEffect(() => {
    loadSettings();
    refreshStatus();

    const interval = window.setInterval(
      refreshStatus,
      3000,
    );

    return () => window.clearInterval(interval);
  }, []);

  if (!settings) {
    return null;
  }

  return (
    <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-600 text-white">
          <Sprout size={24} />
        </div>

        <div className="flex-1">
          <h2 className="text-xl font-semibold text-slate-950">
            Panel Cleaning and Plant Watering
          </h2>

          <p className="mt-1 text-sm text-slate-600">
            Manual control and persistent automatic scheduling.
          </p>
        </div>

        <div
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            status?.running
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-600"
          }`}
        >
          {status?.running ? "Running" : "Idle"}
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <label className="rounded-2xl bg-slate-50 p-4">
          <span className="text-sm font-medium text-slate-700">
            Automatic schedule
          </span>

          <div className="mt-3 flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings.enabled}
              onChange={(event) =>
                updateSetting(
                  "enabled",
                  event.target.checked,
                )
              }
              className="h-5 w-5"
            />

            <span className="text-sm">
              {settings.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
        </label>

        <label className="rounded-2xl bg-slate-50 p-4">
          <span className="text-sm font-medium text-slate-700">
            Run time
          </span>

          <input
            type="time"
            value={settings.run_time}
            onChange={(event) =>
              updateSetting(
                "run_time",
                event.target.value,
              )
            }
            className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2"
          />
        </label>

        <label className="rounded-2xl bg-slate-50 p-4">
          <span className="text-sm font-medium text-slate-700">
            Timezone
          </span>

          <input
            type="text"
            value={settings.timezone}
            onChange={(event) =>
              updateSetting(
                "timezone",
                event.target.value,
              )
            }
            className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2"
          />
        </label>

        {NUMBER_FIELDS.map(([key, label, suffix]) => (
          <label
            key={key}
            className="rounded-2xl bg-slate-50 p-4"
          >
            <span className="text-sm font-medium text-slate-700">
              {label}
            </span>

            <div className="mt-2 flex items-center gap-2">
              <input
                type="number"
                min={key === "frequency_days" ? 1 : 0}
                value={settings[key]}
                onChange={(event) =>
                  updateSetting(
                    key,
                    Number(event.target.value),
                  )
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2"
              />

              <span className="text-xs text-slate-500">
                {suffix}
              </span>
            </div>
          </label>
        ))}
      </div>

      {status?.schedule && (
        <div className="mt-5 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
          Schedule:{" "}
          <strong>
            {status.schedule.enabled
              ? `Every ${status.schedule.frequency_days} day(s) at ${status.schedule.run_time}`
              : "Disabled"}
          </strong>

          {status.schedule.next_scheduled_run && (
            <>
              {" · "}Next:{" "}
              {new Date(
                status.schedule.next_scheduled_run,
              ).toLocaleString()}
            </>
          )}
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={saveSettings}
          disabled={pending !== null}
          className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Save size={17} />
          Save Settings
        </button>

        <button
          type="button"
          disabled={pending !== null || status?.running}
          onClick={() => runCommand("start")}
          className="flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          {pending === "start" ? (
            <LoaderCircle
              size={18}
              className="animate-spin"
            />
          ) : (
            <Play size={18} />
          )}
          Start Now
        </button>

        <button
          type="button"
          disabled={pending !== null || !status?.running}
          onClick={() => runCommand("stop")}
          className="flex items-center gap-2 rounded-xl bg-red-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          <CircleStop size={18} />
          Safe Stop
        </button>
      </div>

      {message && (
        <p className="mt-4 text-sm text-emerald-700">
          {message}
        </p>
      )}

      {error && (
        <p className="mt-4 text-sm text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}