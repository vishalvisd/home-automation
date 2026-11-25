import { useEffect, useState } from "react";
import {
  Lock,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  TerminalSquare,
} from "lucide-react";

import {
  createPassphrase,
  forgetPassphrase,
  getAutomation,
  getAutomations,
  getPassphraseState,
  hasPassphrase,
  restoreAutomation,
  runAutomation,
  saveAutomation,
  unlock,
} from "../services/automationApi";


export default function AutomationsPanel() {
  const [automations, setAutomations] = useState([]);
  const [selected, setSelected] = useState(null);
  const [source, setSource] = useState("");
  const [details, setDetails] = useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  // The scripts are behind a passphrase, checked by the backend.
  //   "checking"  asking the backend whether one has been set
  //   "unset"     none yet: this visit sets it
  //   "locked"    one is set: ask for it
  //   "open"      accepted: show the scripts
  const [gate, setGate] = useState("checking");
  const [typed, setTyped] = useState("");
  const [typedAgain, setTypedAgain] = useState("");
  const [gateError, setGateError] = useState(null);
  const [gateBusy, setGateBusy] = useState(false);

  // The backend no longer accepts the passphrase (it was changed on
  // the Pi, or removed): back to the passphrase screen.
  function lockIfRefused(requestError) {
    if (requestError.status === 401 || requestError.status === 403) {
      forgetPassphrase();
      setGate(requestError.status === 403 ? "unset" : "locked");
      setDetails(null);
      setAutomations([]);
      setSelected(null);
      return true;
    }

    return false;
  }

  function showError(requestError) {
    if (!lockIfRefused(requestError)) {
      setError(requestError.message);
    }
  }

  async function checkGate() {
    try {
      const state = await getPassphraseState();

      if (!state.set) {
        setGate("unset");
      } else if (hasPassphrase()) {
        setGate("open");
        await loadList();
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
      await loadList();
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

  async function loadList() {
    const items = await getAutomations();
    setAutomations(items);

    if (!selected && items.length > 0) {
      await selectAutomation(items[0].key);
    }
  }

  async function selectAutomation(key) {
    setSelected(key);

    const result = await getAutomation(key);

    setDetails(result);
    setSource(result.source);
  }

  async function save() {
    setPending("save");

    try {
      const result = await saveAutomation(
        selected,
        source,
      );

      setDetails(result);
      setMessage("Runtime script saved.");
      setError(null);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setPending(null);
    }
  }

  async function restore() {
    setPending("restore");

    try {
      const result = await restoreAutomation(
        selected,
      );

      setDetails(result);
      setSource(result.source);
      setMessage("Factory script restored.");
      setError(null);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setPending(null);
    }
  }

  async function run() {
    setPending("run");

    try {
      const result = await runAutomation(
        selected,
      );

      setDetails(result);
      setMessage(`${result.name} started.`);
      setError(null);
    } catch (requestError) {
      showError(requestError);
    } finally {
      setPending(null);
    }
  }

  async function refresh() {
    if (!selected) {
      return;
    }

    try {
      const result = await getAutomation(selected);

      setDetails(result);
    } catch (requestError) {
      showError(requestError);
    }

    // Do not overwrite unsaved editor contents.
  }

  useEffect(() => {
    checkGate().catch(showError);
  }, []);

  return (
    <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white">
          <TerminalSquare size={23} />
        </div>

        <div>
          <h2 className="text-xl font-semibold text-slate-950">
            Automations
          </h2>

          <p className="mt-1 text-sm text-slate-600">
            View, temporarily edit, restore and run Python automation scripts.
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
            {gate === "unset"
              ? "Set a passphrase"
              : "Passphrase"}
          </div>

          <p className="mt-2 text-sm text-slate-600">
            {gate === "unset"
              ? "The scripts can run anything on the Pi, so they are kept behind a passphrase. None is set yet: choose one now."
              : "Type the passphrase to see, edit and run the scripts."}
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
            <code>runtime/automation_passphrase.json</code>. This page
            then asks for a new one.
          </p>
        </form>
      )}

      <div className="mt-6 flex flex-wrap gap-2">
        {automations.map((automation) => (
          <button
            key={automation.key}
            type="button"
            onClick={() =>
              selectAutomation(automation.key)
            }
            className={`rounded-xl px-4 py-2 text-sm font-semibold ${
              selected === automation.key
                ? "bg-slate-900 text-white"
                : "bg-slate-100 text-slate-700"
            }`}
          >
            {automation.name}
          </button>
        ))}
      </div>

      {details && (
        <>
          <div className="mt-5 flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-slate-900">
                {details.name}
              </h3>

              <p className="text-sm text-slate-500">
                {details.description}
              </p>
            </div>

            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                details.running
                  ? "bg-amber-100 text-amber-700"
                  : "bg-slate-100 text-slate-600"
              }`}
            >
              {details.running ? "Running" : "Idle"}
            </span>
          </div>

          <textarea
            value={source}
            onChange={(event) =>
              setSource(event.target.value)
            }
            spellCheck="false"
            className="mt-4 h-96 w-full rounded-2xl border border-slate-200 bg-slate-950 p-4 font-mono text-sm text-slate-100"
          />

          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={save}
              disabled={pending !== null}
              className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              <Save size={17} />
              Save Runtime Copy
            </button>

            <button
              type="button"
              onClick={restore}
              disabled={pending !== null}
              className="flex items-center gap-2 rounded-xl bg-slate-100 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50"
            >
              <RotateCcw size={17} />
              Restore Default
            </button>

            <button
              type="button"
              onClick={run}
              disabled={
                pending !== null || details.running
              }
              className="flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              <Play size={17} />
              Run Now
            </button>

            <button
              type="button"
              onClick={refresh}
              className="flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700"
            >
              <RefreshCw size={17} />
              Refresh Status
            </button>
          </div>

          {details.last_output && (
            <pre className="mt-4 overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-200">
              {details.last_output}
            </pre>
          )}
        </>
      )}

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