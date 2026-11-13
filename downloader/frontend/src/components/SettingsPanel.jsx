import { useEffect, useState } from "react";
import { Plug, Save } from "lucide-react";

import { api } from "../api";
import { Button, Card, Field, Message, inputClass } from "./ui";

export default function SettingsPanel({ system, onSaved }) {
  const [form, setForm] = useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getSettings().then(setForm).catch((e) => setError(e.message));
  }, []);

  function set(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setPending("save");
    setMessage(null);
    setError(null);
    try {
      const saved = await api.saveSettings(form);
      setForm(saved);
      setMessage("Settings saved.");
      onSaved?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(null);
    }
  }

  async function test() {
    setPending("test");
    setMessage(null);
    setError(null);
    try {
      const result = await api.testConnection();
      setMessage(
        `Connected to bucket "${result.bucket}". Cameras found: ${
          result.cameras.length ? result.cameras.join(", ") : "none yet"
        }.`,
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(null);
    }
  }

  if (!form) return null;

  return (
    <div className="space-y-4">
      <Card
        title="Backblaze B2"
        subtitle="Use an application key restricted to the CCTV bucket. The key is stored only on this computer, in downloader/runtime/settings.json."
      >
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <Field label="Bucket">
            <input className={`${inputClass} font-mono`} value={form.b2_bucket} onChange={(e) => set("b2_bucket", e.target.value)} placeholder="visd-cctv-eu" />
          </Field>
          <Field label="Application key ID">
            <input className={`${inputClass} font-mono`} value={form.b2_key_id} onChange={(e) => set("b2_key_id", e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Application key" hint={form.b2_application_key_set ? "A key is saved. Enter a new one only to replace it." : "Not set yet."}>
            <input type="password" className={`${inputClass} font-mono`} value={form.b2_application_key} onChange={(e) => set("b2_application_key", e.target.value)} autoComplete="new-password" placeholder={form.b2_application_key_set ? "••••••••" : ""} />
          </Field>
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button icon={Save} onClick={save} busy={pending === "save"} disabled={pending !== null}>Save Settings</Button>
          <Button icon={Plug} variant="secondary" onClick={test} busy={pending === "test"} disabled={pending !== null || !system?.b2_configured}>Test Connection</Button>
        </div>
        <Message error={error} message={message} />
      </Card>

      <Card title="Folders and tools">
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field label="Output folder" hint="Joined videos and time-lapses are saved here.">
            <input className={`${inputClass} font-mono`} value={form.output_directory} onChange={(e) => set("output_directory", e.target.value)} />
          </Field>
          <Field label="ffmpeg location" hint={system?.ffmpeg_available ? `Found: ${system.ffmpeg_path}` : "Not found. Install ffmpeg or give the folder or file path here."}>
            <input className={`${inputClass} font-mono`} value={form.ffmpeg_path} onChange={(e) => set("ffmpeg_path", e.target.value)} placeholder="leave empty if ffmpeg is on PATH" />
          </Field>
          <Field label="Parallel downloads">
            <input type="number" min={1} max={16} className={inputClass} value={form.parallel_downloads} onChange={(e) => set("parallel_downloads", Number(e.target.value))} />
          </Field>
          <Field label="Clip length on the Pi (seconds)" hint="Must match segment_seconds in the Pi settings. Clip names carry the end time; this is used to work out the start.">
            <input type="number" min={10} className={inputClass} value={form.segment_seconds} onChange={(e) => set("segment_seconds", Number(e.target.value))} />
          </Field>
          <Field label="Clip timezone" hint="Timezone used in clip names on the Pi.">
            <input className={`${inputClass} font-mono`} value={form.clip_timezone} onChange={(e) => set("clip_timezone", e.target.value)} />
          </Field>
        </div>
        {system && (
          <p className="mt-4 text-xs text-slate-500">
            Platform {system.platform}. Video encoders available, in the order they are tried:{" "}
            <span className="font-mono">{system.video_encoders?.join(", ") || "none"}</span>
          </p>
        )}
        <div className="mt-5">
          <Button icon={Save} onClick={save} busy={pending === "save"} disabled={pending !== null}>Save Settings</Button>
        </div>
      </Card>
    </div>
  );
}
