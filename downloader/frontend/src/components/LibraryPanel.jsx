import { useEffect, useState } from "react";
import { Film, FolderOpen, Play, RefreshCw, Trash2, X } from "lucide-react";

import { api, formatBytes } from "../api";
import { Badge, Button, Card, Field, Message, inputClass } from "./ui";

const SPEEDS = [1, 2, 4, 8, 10, 15, 20, 30, 60];

export default function LibraryPanel({ system, onJobStarted }) {
  const [library, setLibrary] = useState({ directory: "", files: [] });
  const [playing, setPlaying] = useState(null);
  const [lapse, setLapse] = useState(null); // file being configured for time-lapse
  const [speed, setSpeed] = useState(10);
  const [fps, setFps] = useState(30);
  const [hevc, setHevc] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      setLibrary(await api.library());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 5000);
    return () => window.clearInterval(interval);
  }, []);

  async function act(fn, success) {
    setError(null);
    setMessage(null);
    try {
      await fn();
      if (success) setMessage(success);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function startTimelapse(file, chosenSpeed) {
    await act(
      () => api.startTimelapse({ source_path: file.path, speed: chosenSpeed, fps, prefer_hevc: hevc }),
      chosenSpeed === 1 ? "Conversion started. See the Jobs tab." : "Time-lapse started. See the Jobs tab.",
    );
    setLapse(null);
    onJobStarted?.();
  }

  return (
    <Card
      title="Library"
      subtitle={library.directory ? `Files in ${library.directory}` : "Output folder"}
      right={
        <div className="flex gap-2">
          <Button icon={FolderOpen} variant="secondary" onClick={() => act(() => api.openFolder(library.directory))}>Open folder</Button>
          <Button icon={RefreshCw} variant="secondary" onClick={refresh}>Refresh</Button>
        </div>
      }
    >
      <Message error={error} message={message} />

      {playing && (
        <div className="mt-4 rounded-2xl bg-slate-950 p-3">
          <div className="flex items-center justify-between text-xs text-slate-300">
            <span className="font-mono">{playing.name}</span>
            <button type="button" onClick={() => setPlaying(null)} className="flex items-center gap-1"><X size={14} /> close</button>
          </div>
          <video key={playing.path} controls autoPlay className="mt-2 w-full rounded-xl" src={api.fileUrl(playing.path)} />
        </div>
      )}

      {lapse && (
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-semibold text-slate-900">Time-lapse of {lapse.name}</div>
          <div className="mt-3 grid gap-4 md:grid-cols-3">
            <Field label="Speed">
              <select className={inputClass} value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                {SPEEDS.map((s) => <option key={s} value={s}>{s === 1 ? "1x (convert only, keeps audio)" : `${s}x`}</option>)}
              </select>
            </Field>
            <Field label="Output frame rate">
              <input type="number" min={1} max={120} className={inputClass} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
            </Field>
            <label className="flex items-center gap-3 pt-7 text-sm text-slate-700">
              <input type="checkbox" className="h-5 w-5" checked={hevc} onChange={(e) => setHevc(e.target.checked)} />
              Prefer HEVC (smaller file)
            </label>
          </div>
          <div className="mt-4 flex gap-2">
            <Button icon={Film} onClick={() => startTimelapse(lapse, speed)} disabled={!system?.ffmpeg_available}>Start</Button>
            <Button variant="secondary" onClick={() => setLapse(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {library.files.length === 0 && <p className="text-sm text-slate-500">No videos yet. Download a window from the Browse tab.</p>}
        {library.files.map((file) => (
          <div key={file.path} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 p-3">
            <div className="min-w-0">
              <div className="truncate font-mono text-sm text-slate-900">{file.name}</div>
              <div className="mt-1 text-xs text-slate-500">{formatBytes(file.size)} · {file.modified.replace("T", " ")}</div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={file.playable ? "blue" : "slate"}>{file.extension}</Badge>
              {file.playable ? (
                <Button variant="subtle" icon={Play} className="px-3 py-1.5 text-xs" onClick={() => setPlaying(file)}>Play</Button>
              ) : (
                <Button variant="subtle" className="px-3 py-1.5 text-xs" onClick={() => startTimelapse(file, 1)}>Convert to MP4</Button>
              )}
              <Button variant="subtle" icon={Film} className="px-3 py-1.5 text-xs" onClick={() => setLapse(file)}>Time-lapse</Button>
              <Button variant="subtle" icon={FolderOpen} className="px-3 py-1.5 text-xs" onClick={() => act(() => api.openFolder(file.path))}>Show</Button>
              <Button variant="subtle" icon={Trash2} className="px-3 py-1.5 text-xs" onClick={() => { if (window.confirm(`Delete ${file.name}?`)) act(() => api.deleteFile(file.path), "Deleted."); }}>Delete</Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
