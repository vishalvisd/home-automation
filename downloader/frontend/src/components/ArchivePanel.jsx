import { useEffect, useState } from "react";
import { Play, Save } from "lucide-react";

import { api } from "../api";
import { Badge, Button, Card, Field, Message, inputClass } from "./ui";

export default function ArchivePanel() {
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      setStatus(await api.archiveStatus());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    api.getSettings()
      .then((s) => setForm({
        archive_enabled: s.archive_enabled,
        archive_directory: s.archive_directory,
        archive_time: s.archive_time,
        archive_keep_days: s.archive_keep_days,
      }))
      .catch((e) => setError(e.message));
    const interval = window.setInterval(refresh, 5000);
    return () => window.clearInterval(interval);
  }, []);

  async function save() {
    setPending("save");
    setMessage(null);
    setError(null);
    try {
      await api.saveSettings(form);
      setMessage("Archive settings saved.");
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(null);
    }
  }

  async function runNow() {
    setPending("run");
    setMessage(null);
    setError(null);
    try {
      await api.runArchive();
      setMessage("Archive job started. See the Jobs tab.");
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(null);
    }
  }

  if (!form) return null;

  return (
    <Card
      title="Local archive"
      subtitle="B2 keeps clips for only a few days. The archive copies every clip in the bucket to a local folder, keeping the same camN/YYYY/MM/DD layout, and skips files it already has."
      right={status && <Badge tone={status.running ? "blue" : status.enabled ? "green" : "slate"}>{status.running ? "Running" : status.enabled ? "Scheduled daily" : "Off"}</Badge>}
    >
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="flex items-center gap-3 rounded-2xl bg-slate-50 p-4 text-sm font-medium text-slate-700">
          <input type="checkbox" className="h-5 w-5" checked={form.archive_enabled} onChange={(e) => setForm({ ...form, archive_enabled: e.target.checked })} />
          Run the archive automatically every day
        </label>
        <Field label="Run at (local time on this computer)" hint="The app must be running at that time.">
          <input type="time" className={inputClass} value={form.archive_time} onChange={(e) => setForm({ ...form, archive_time: e.target.value })} />
        </Field>
        <Field label="Archive folder" hint="An external disk is a good choice.">
          <input className={`${inputClass} font-mono`} value={form.archive_directory} onChange={(e) => setForm({ ...form, archive_directory: e.target.value })} />
        </Field>
        <Field label="Keep for (days)" hint="0 keeps everything forever. Otherwise day folders older than this are deleted after each run.">
          <input type="number" min={0} className={inputClass} value={form.archive_keep_days} onChange={(e) => setForm({ ...form, archive_keep_days: Number(e.target.value) })} />
        </Field>
      </div>

      {status && (
        <p className="mt-4 text-xs text-slate-500">
          Last run: {status.last_run_date ?? "never"}.
        </p>
      )}

      <div className="mt-5 flex flex-wrap gap-3">
        <Button icon={Save} onClick={save} busy={pending === "save"} disabled={pending !== null}>Save</Button>
        <Button icon={Play} variant="secondary" onClick={runNow} busy={pending === "run"} disabled={pending !== null || status?.running}>Run archive now</Button>
      </div>
      <Message error={error} message={message} />
    </Card>
  );
}
