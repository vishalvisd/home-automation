import { useEffect, useRef, useState } from "react";
import {
  Download,
  Lock,
  Mic,
  Save,
  Square,
  Trash2,
  Volume2,
} from "lucide-react";

import {
  createPassphrase,
  downloadMicSound,
  forgetPassphrase,
  getMicSettings,
  getMicStatus,
  getPassphraseState,
  hasPassphrase,
  removeMicModule,
  saveMicModule,
  saveMicSettings,
  unlock,
} from "../services/micApi";
import { startMicLive } from "../services/micLivePlayer";


const REFRESH_SECONDS = 5;

// Clock times are shown and typed in India time, wherever the browser
// is. India has no summer time, so the difference never changes.
const INDIA_OFFSET_SECONDS = 5.5 * 3600;

const SETTING_FIELDS = [
  ["keep_minutes", "Keep the last", "minutes of every module"],
  ["ram_limit_mb", "All modules together may use", "MB of RAM"],
  ["opus_bitrate_kbps", "Stored sound quality", "kbps (Opus)"],
];

const QUICK_RANGES = [
  ["Last 5 min", 5],
  ["Last 15 min", 15],
  ["Last hour", 60],
];


function clock(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Kolkata",
  });
}


function clockOfIso(text) {
  return text ? clock(new Date(text).getTime() / 1000) : "never";
}


function span(seconds) {
  const whole = Math.max(0, Math.round(seconds));

  if (whole < 60) {
    return `${whole} s`;
  }

  if (whole < 3600) {
    return `${Math.floor(whole / 60)} min ${whole % 60} s`;
  }

  const minutes = Math.floor((whole % 3600) / 60);

  return minutes === 0
    ? `${Math.floor(whole / 3600)} h`
    : `${Math.floor(whole / 3600)} h ${minutes} min`;
}


// "18:40:00" typed as India time -> seconds since 1970. A time that is
// still to come today is taken as yesterday's.
function epochOfClock(text) {
  const [hours, minutes, seconds = 0] = text.split(":").map(Number);

  if (Number.isNaN(hours) || Number.isNaN(minutes)) {
    return null;
  }

  const now = Date.now() / 1000;
  const indiaMidnight =
    Math.floor((now + INDIA_OFFSET_SECONDS) / 86400) * 86400
    - INDIA_OFFSET_SECONDS;

  let moment = indiaMidnight + hours * 3600 + minutes * 60 + seconds;

  if (moment > now + 60) {
    moment -= 86400;
  }

  return moment;
}


function signalWord(dbm) {
  if (dbm === 0) {
    return "not connected";
  }

  if (dbm >= -67) {
    return "good";
  }

  return dbm >= -75 ? "fair" : "weak";
}


export default function MicPanel({ active }) {
  // The microphones are behind a passphrase of their own, checked by
  // the backend.
  //   "checking"  asking the backend whether one has been set
  //   "unset"     none yet: this visit sets it
  //   "locked"    one is set: ask for it
  //   "open"      accepted
  const [gate, setGate] = useState("checking");
  const [typed, setTyped] = useState("");
  const [typedAgain, setTypedAgain] = useState("");
  const [gateError, setGateError] = useState(null);
  const [gateBusy, setGateBusy] = useState(false);

  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [names, setNames] = useState({});
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  // Live listening: one module at a time.
  const [liveModule, setLiveModule] = useState(null);
  const [livePeak, setLivePeak] = useState(0);
  const [loudness, setLoudness] = useState(8);
  const [level, setLevel] = useState(true);
  const player = useRef(null);

  // Download: one module's form is open at a time.
  const [downloadModule, setDownloadModule] = useState(null);
  const [fromClock, setFromClock] = useState("");
  const [toClock, setToClock] = useState("");
  const [format, setFormat] = useState("mp3");
  const [levelDownload, setLevelDownload] = useState(true);

  function stopLive() {
    if (player.current) {
      player.current.stop();
      player.current = null;
    }

    setLiveModule(null);
    setLivePeak(0);
  }

  // The backend no longer accepts the passphrase (it was removed on
  // the Pi): back to the passphrase screen.
  function lockIfRefused(requestError) {
    if (requestError.status === 401 || requestError.status === 403) {
      stopLive();
      forgetPassphrase();
      setGate(requestError.status === 403 ? "unset" : "locked");
      setStatus(null);
      setSettings(null);
      return true;
    }

    return false;
  }

  function showError(requestError) {
    if (!lockIfRefused(requestError)) {
      setMessage(null);
      setError(requestError.message);
    }
  }

  async function refreshStatus() {
    try {
      setStatus(await getMicStatus());
    } catch (requestError) {
      showError(requestError);
    }
  }

  async function loadAll() {
    setSettings(await getMicSettings());
    setStatus(await getMicStatus());
  }

  async function checkGate() {
    try {
      const state = await getPassphraseState();

      if (!state.set) {
        setGate("unset");
      } else if (hasPassphrase()) {
        setGate("open");
        await loadAll();
      } else {
        setGate("locked");
      }
    } catch (requestError) {
      setGateError(requestError.message);
    }
  }

  async function submitPassphrase(event) {
    event.preventDefault();

    if (gate === "unset" && typed !== typedAgain) {
      setGateError("The two passphrases are not the same.");
      return;
    }

    setGateBusy(true);
    setGateError(null);

    try {
      if (gate === "unset") {
        await createPassphrase(typed);
      } else {
        await unlock(typed);
      }

      setTyped("");
      setTypedAgain("");
      setGate("open");
      await loadAll();
    } catch (requestError) {
      // 409: someone set one in the meantime. Ask for it instead.
      if (requestError.status === 409) {
        setGate("locked");
      }

      setGateError(requestError.message);
    } finally {
      setGateBusy(false);
    }
  }

  async function act(key, work, done) {
    setPending(key);

    try {
      await work();
      setError(null);
      setMessage(done);
      await refreshStatus();
    } catch (requestError) {
      showError(requestError);
    } finally {
      setPending(null);
    }
  }

  function saveSettings() {
    act(
      "settings",
      async () => {
        setSettings(
          await saveMicSettings({
            enabled: settings.enabled,
            keep_minutes: Number(settings.keep_minutes),
            ram_limit_mb: Number(settings.ram_limit_mb),
            opus_bitrate_kbps: Number(settings.opus_bitrate_kbps),
          }),
        );
      },
      "Settings saved.",
    );
  }

  function saveName(module) {
    act(
      `name-${module.id}`,
      async () => {
        await saveMicModule(module.id, {
          name: names[module.id] ?? module.name,
          enabled: module.enabled,
        });

        setNames((current) => {
          const next = { ...current };
          delete next[module.id];
          return next;
        });
      },
      "Room name saved.",
    );
  }

  function switchModule(module) {
    if (module.enabled && liveModule === module.id) {
      stopLive();
    }

    act(
      `switch-${module.id}`,
      () =>
        saveMicModule(module.id, {
          name: module.name,
          enabled: !module.enabled,
        }),
      module.enabled
        ? "Module switched off. Its sound is no longer stored."
        : "Module switched on.",
    );
  }

  function removeModule(module) {
    const sure = window.confirm(
      `Remove ${module.name || module.id} from the list and delete its `
        + "stored sound? A module that still has power calls again "
        + "within seconds and is added as a new one.",
    );

    if (!sure) {
      return;
    }

    if (liveModule === module.id) {
      stopLive();
    }

    act(
      `remove-${module.id}`,
      () => removeMicModule(module.id),
      "Module removed.",
    );
  }

  function toggleLive(module) {
    if (liveModule === module.id) {
      stopLive();
      return;
    }

    stopLive();
    setError(null);
    setLiveModule(module.id);

    player.current = startMicLive(module.id, {
      loudness,
      level,
      onLevel: (peak) => setLivePeak(peak),
      onStop: (stopError) => {
        player.current = null;
        setLiveModule(null);
        setLivePeak(0);

        if (stopError) {
          showError(stopError);
        }
      },
    });
  }

  function changeLoudness(value) {
    setLoudness(value);

    if (player.current) {
      player.current.setLoudness(value);
    }
  }

  function changeLevel(value) {
    setLevel(value);

    if (player.current) {
      player.current.setLevel(value);
    }
  }

  function setRange(start, end) {
    setFromClock(clock(start));
    setToClock(clock(end));
  }

  function openDownload(module) {
    if (downloadModule === module.id) {
      setDownloadModule(null);
      return;
    }

    const now = Date.now() / 1000;

    setRange(now - 300, now);
    setDownloadModule(module.id);
  }

  function download(module) {
    const start = epochOfClock(fromClock);
    let end = epochOfClock(toClock);

    if (start === null || end === null) {
      setError("Give a start and an end time.");
      return;
    }

    // "23:50 to 00:10": the end is on the next day.
    if (end <= start) {
      end += 86400;
    }

    act(
      `download-${module.id}`,
      async () => {
        const file = await downloadMicSound(module.id, {
          start,
          end,
          format,
          level: format === "mp3" && levelDownload,
        });

        const address = URL.createObjectURL(file.blob);
        const link = document.createElement("a");

        link.href = address;
        link.download = file.name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(address), 60000);
      },
      "Download ready.",
    );
  }

  useEffect(() => {
    checkGate().catch(showError);

    return () => {
      if (player.current) {
        player.current.stop();
      }
    };
    // Runs once, when the page loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (gate !== "open" || !active) {
      return undefined;
    }

    refreshStatus();

    const timer = window.setInterval(
      refreshStatus,
      REFRESH_SECONDS * 1000,
    );

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gate, active]);

  const storage = status?.storage;

  return (
    <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white">
          <Mic size={23} />
        </div>

        <div>
          <h2 className="text-xl font-semibold text-slate-950">
            Microphones
          </h2>

          <p className="mt-1 text-sm text-slate-600">
            The room microphone modules. The Pi keeps the last
            {" "}{storage ? span(storage.keep_minutes * 60) : "two hours"}{" "}
            of every module in RAM. Listen live, or download a stretch
            of it.
          </p>
        </div>
      </div>

      {gate === "checking" && gateError && (
        <p className="mt-6 text-sm text-red-700">{gateError}</p>
      )}

      {(gate === "unset" || gate === "locked") && (
        <form
          onSubmit={submitPassphrase}
          className="mt-6 max-w-md rounded-2xl border border-slate-200 bg-slate-50 p-5"
        >
          <div className="flex items-center gap-2 font-semibold text-slate-900">
            <Lock size={17} />
            {gate === "unset" ? "Set a passphrase" : "Passphrase"}
          </div>

          <p className="mt-2 text-sm text-slate-600">
            {gate === "unset"
              ? "This is the sound of rooms, so it is kept behind a passphrase of its own. None is set yet: choose one now."
              : "Type the microphone passphrase to see the modules, listen and download."}
          </p>

          <input
            type="password"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Passphrase"
            autoComplete={
              gate === "unset" ? "new-password" : "current-password"
            }
            className="mt-4 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
          />

          {gate === "unset" && (
            <input
              type="password"
              value={typedAgain}
              onChange={(event) => setTypedAgain(event.target.value)}
              placeholder="The same passphrase again"
              autoComplete="new-password"
              className="mt-3 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          )}

          <button
            type="submit"
            disabled={gateBusy || typed.length === 0}
            className="mt-4 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {gate === "unset" ? "Set passphrase" : "Open"}
          </button>

          {gateError && (
            <p className="mt-3 text-sm text-red-700">{gateError}</p>
          )}

          <p className="mt-4 text-xs text-slate-500">
            Forgotten? On the Pi, delete{" "}
            <code>runtime/mic_passphrase.json</code>. This page then
            asks for a new one. It is not the automation passphrase.
          </p>
        </form>
      )}

      {gate === "open" && status && (
        <>
          <div className="mt-6 flex flex-wrap gap-2 text-sm">
            <span
              className={`rounded-full px-3 py-1 font-semibold ${
                status.listening
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-red-100 text-red-700"
              }`}
            >
              {status.listening
                ? `Waiting for modules on port ${status.port}`
                : status.enabled
                  ? "Not receiving"
                  : "Switched off"}
            </span>

            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
              Stored: {storage.used_mb} of {storage.ram_limit_mb} MB
            </span>

            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
              RAM disk free: {storage.ram_free_mb} MB
            </span>

            {storage.deleted_for_ram > 0 && (
              <span className="rounded-full bg-amber-100 px-3 py-1 text-amber-700">
                Gave way to the cameras: {storage.deleted_for_ram} min,
                last at {clockOfIso(storage.last_gave_way_at)}
              </span>
            )}
          </div>

          {status.last_error && (
            <p className="mt-3 text-sm text-red-700">{status.last_error}</p>
          )}

          {!status.ffmpeg_found && (
            <p className="mt-3 text-sm text-red-700">
              ffmpeg is not installed on the Pi, so no sound is stored.
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl bg-slate-50 p-4 text-sm text-slate-700">
            <span className="font-semibold text-slate-900">
              Live listening
            </span>

            <label className="flex items-center gap-2">
              Loudness
              <input
                type="range"
                min="1"
                max="40"
                step="1"
                value={loudness}
                onChange={(event) =>
                  changeLoudness(Number(event.target.value))
                }
              />
              <span className="w-10">{loudness}x</span>
            </label>

            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={level}
                onChange={(event) => changeLevel(event.target.checked)}
              />
              Level the volume
            </label>

            <span className="text-xs text-slate-500">
              The sound is stored as the module sends it, which is
              quiet. These only change what you hear.
            </span>
          </div>

          {status.modules.length === 0 && (
            <p className="mt-6 text-sm text-slate-600">
              No module has called yet. A module that has power and
              Wi-Fi appears here by itself within seconds.
            </p>
          )}

          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            {status.modules.map((module) => {
              const health = module.health || {};
              const signal = Number(health.wifi_signal || 0);
              const stored = module.stored;
              const stretches = stored ? stored.stretches : [];
              const isLive = liveModule === module.id;
              const light = !module.connected
                ? "bg-red-500"
                : module.enabled && module.recording
                  ? "bg-emerald-500"
                  : "bg-amber-400";

              return (
                <div
                  key={module.id}
                  className="rounded-2xl border border-slate-200 p-5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className={`h-3 w-3 rounded-full ${light}`} />

                      <div>
                        <h3 className="font-semibold text-slate-900">
                          {module.name || module.id}
                        </h3>

                        <p className="text-xs text-slate-500">
                          {module.id}
                          {" · "}
                          {!module.connected
                            ? "not connected"
                            : !module.enabled
                              ? "connected, switched off"
                              : module.recording
                                ? "connected, storing"
                                : "connected, not storing"}
                        </p>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => switchModule(module)}
                      disabled={pending !== null}
                      className={`rounded-xl px-3 py-2 text-xs font-semibold disabled:opacity-50 ${
                        module.enabled
                          ? "bg-emerald-600 text-white"
                          : "bg-slate-200 text-slate-700"
                      }`}
                    >
                      {module.enabled ? "On" : "Off"}
                    </button>
                  </div>

                  {module.recorder_error && (
                    <p className="mt-3 text-sm text-red-700">
                      {module.recorder_error}
                    </p>
                  )}

                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    {module.connected ? (
                      <>
                        <dt className="text-slate-500">Wi-Fi signal</dt>
                        <dd className="text-slate-900">
                          {signal} dBm ({signalWord(signal)})
                        </dd>

                        <dt className="text-slate-500">Microphone level</dt>
                        <dd className="text-slate-900">
                          {health.mic_peak ?? "?"} of 32767
                          {health.mic_peak === "0" && " (no sound: check the wires)"}
                        </dd>

                        <dt className="text-slate-500">Firmware</dt>
                        <dd className="text-slate-900">
                          {module.firmware_version || "?"}
                          {health.trial === "yes" && " (on trial)"}
                        </dd>

                        <dt className="text-slate-500">Running for</dt>
                        <dd className="text-slate-900">
                          {health.uptime ? span(Number(health.uptime)) : "?"}
                        </dd>

                        <dt className="text-slate-500">Connected since</dt>
                        <dd className="text-slate-900">
                          {clockOfIso(module.connected_at)}
                        </dd>

                        <dt className="text-slate-500">Sound lost on the way</dt>
                        <dd className="text-slate-900">
                          {span((module.frames_lost || 0) * 0.016)}
                        </dd>
                      </>
                    ) : (
                      <>
                        <dt className="text-slate-500">First seen</dt>
                        <dd className="text-slate-900">
                          {clockOfIso(module.first_seen_at)}
                        </dd>
                      </>
                    )}

                    <dt className="text-slate-500">Stored</dt>
                    <dd className="text-slate-900">
                      {stored
                        ? `${stored.mb} MB, since ${clockOfIso(stored.oldest_at)}`
                        : "nothing"}
                    </dd>
                  </dl>

                  <div className="mt-4 flex gap-2">
                    <input
                      type="text"
                      value={names[module.id] ?? module.name}
                      onChange={(event) =>
                        setNames({
                          ...names,
                          [module.id]: event.target.value,
                        })
                      }
                      placeholder="Room name"
                      maxLength={40}
                      className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm"
                    />

                    <button
                      type="button"
                      onClick={() => saveName(module)}
                      disabled={
                        pending !== null
                        || (names[module.id] ?? module.name) === module.name
                      }
                      className="flex items-center gap-2 rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                    >
                      <Save size={15} />
                      Save
                    </button>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => toggleLive(module)}
                      disabled={!module.enabled || !module.connected}
                      className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 ${
                        isLive
                          ? "bg-red-600 text-white"
                          : "bg-emerald-600 text-white"
                      }`}
                    >
                      {isLive ? <Square size={15} /> : <Volume2 size={15} />}
                      {isLive ? "Stop listening" : "Listen live"}
                    </button>

                    <button
                      type="button"
                      onClick={() => openDownload(module)}
                      disabled={!stored}
                      className="flex items-center gap-2 rounded-xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
                    >
                      <Download size={15} />
                      Download
                    </button>

                    <button
                      type="button"
                      onClick={() => removeModule(module)}
                      disabled={pending !== null}
                      className="ml-auto flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 disabled:opacity-50"
                    >
                      <Trash2 size={15} />
                      Remove
                    </button>
                  </div>

                  {isLive && (
                    <div className="mt-3">
                      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full bg-emerald-500 transition-all"
                          style={{
                            width: `${Math.min(100, (livePeak * loudness * 100) / 32767)}%`,
                          }}
                        />
                      </div>

                      <p className="mt-1 text-xs text-slate-500">
                        Live, about half a second behind. The bar moves
                        with the sound that arrives.
                      </p>
                    </div>
                  )}

                  {downloadModule === module.id && stored && (
                    <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm">
                      <p className="font-semibold text-slate-900">
                        What is stored (India time)
                      </p>

                      <ul className="mt-2 space-y-1 text-slate-700">
                        {stretches.length > 6 && (
                          <li className="text-slate-500">
                            {stretches.length - 6} earlier stretch(es)
                            not shown
                          </li>
                        )}

                        {stretches.slice(-6).map((stretch) => (
                          <li key={stretch.start}>
                            <button
                              type="button"
                              onClick={() =>
                                setRange(stretch.start, stretch.end)
                              }
                              className="underline decoration-slate-300"
                            >
                              {clock(stretch.start)} to {clock(stretch.end)}
                            </button>
                            {" "}({span(stretch.end - stretch.start)})
                          </li>
                        ))}
                      </ul>

                      {stretches.length > 1 && (
                        <p className="mt-2 text-xs text-slate-500">
                          Between two stretches nothing is stored. A
                          download that covers such a hole leaves it
                          out, so the file is shorter than the time
                          asked for.
                        </p>
                      )}

                      <div className="mt-4 flex flex-wrap items-end gap-3">
                        <label className="block">
                          <span className="text-slate-600">From</span>
                          <input
                            type="time"
                            step="1"
                            value={fromClock}
                            onChange={(event) =>
                              setFromClock(event.target.value)
                            }
                            className="mt-1 block rounded-xl border border-slate-300 bg-white px-3 py-2"
                          />
                        </label>

                        <label className="block">
                          <span className="text-slate-600">To</span>
                          <input
                            type="time"
                            step="1"
                            value={toClock}
                            onChange={(event) =>
                              setToClock(event.target.value)
                            }
                            className="mt-1 block rounded-xl border border-slate-300 bg-white px-3 py-2"
                          />
                        </label>

                        <div className="flex flex-wrap gap-2">
                          {QUICK_RANGES.map(([label, minutes]) => (
                            <button
                              key={label}
                              type="button"
                              onClick={() => {
                                const now = Date.now() / 1000;
                                setRange(now - minutes * 60, now);
                              }}
                              className="rounded-xl bg-white px-3 py-2 text-xs font-semibold text-slate-700 ring-1 ring-slate-200"
                            >
                              {label}
                            </button>
                          ))}

                          <button
                            type="button"
                            onClick={() =>
                              setRange(
                                stretches[0].start,
                                Date.now() / 1000,
                              )
                            }
                            disabled={stretches.length === 0}
                            className="rounded-xl bg-white px-3 py-2 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 disabled:opacity-50"
                          >
                            Everything
                          </button>
                        </div>
                      </div>

                      <div className="mt-4 flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-2">
                          File
                          <select
                            value={format}
                            onChange={(event) =>
                              setFormat(event.target.value)
                            }
                            className="rounded-xl border border-slate-300 bg-white px-3 py-2"
                          >
                            <option value="mp3">
                              MP3 (plays everywhere)
                            </option>
                            <option value="opus">
                              Opus (as stored, not converted)
                            </option>
                          </select>
                        </label>

                        <label className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={format === "mp3" && levelDownload}
                            disabled={format !== "mp3"}
                            onChange={(event) =>
                              setLevelDownload(event.target.checked)
                            }
                          />
                          Level the volume
                        </label>

                        <button
                          type="button"
                          onClick={() => download(module)}
                          disabled={pending !== null}
                          className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50"
                        >
                          <Download size={15} />
                          {pending === `download-${module.id}`
                            ? "Making the file..."
                            : "Download"}
                        </button>
                      </div>

                      <p className="mt-3 text-xs text-slate-500">
                        Nothing is kept on the Pi beyond the time above.
                        A download is the only way to keep a recording.
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {settings && (
            <div className="mt-6 rounded-2xl border border-slate-200 p-5">
              <h3 className="font-semibold text-slate-900">Settings</h3>

              <label className="mt-4 flex items-center gap-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={settings.enabled}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      enabled: event.target.checked,
                    })
                  }
                />
                Receive and store the modules' sound. Off closes the
                port the modules call, for all of them.
              </label>

              <div className="mt-4 grid gap-4 md:grid-cols-3">
                {SETTING_FIELDS.map(([key, label, unit]) => (
                  <label key={key} className="block text-sm">
                    <span className="text-slate-600">{label}</span>

                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="number"
                        value={settings[key]}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            [key]: event.target.value,
                          })
                        }
                        className="w-24 rounded-xl border border-slate-300 px-3 py-2"
                      />
                      <span className="text-slate-500">{unit}</span>
                    </div>
                  </label>
                ))}
              </div>

              <p className="mt-3 text-xs text-slate-500">
                When the limit is reached the oldest minute goes first,
                from all modules alike. If the RAM disk has less than{" "}
                {storage.gives_way_under_mb} MB free, the microphone
                sound gives way so that no camera clip is dropped. A
                new sound quality applies the next time a module
                connects.
              </p>

              <button
                type="button"
                onClick={saveSettings}
                disabled={pending !== null}
                className="mt-4 flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
              >
                <Save size={17} />
                Save settings
              </button>
            </div>
          )}
        </>
      )}

      {message && (
        <p className="mt-4 text-sm text-emerald-700">{message}</p>
      )}

      {error && (
        <p className="mt-4 text-sm text-red-700">{error}</p>
      )}
    </section>
  );
}
