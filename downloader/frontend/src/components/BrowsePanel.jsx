import { useEffect, useState } from "react";
import { Download, Play, RefreshCw, X } from "lucide-react";

import { api, formatBytes, timeOnly } from "../api";
import { Badge, Button, Card, Field, Message, inputClass } from "./ui";

const DURATIONS = [
  [10, "10 minutes"], [30, "30 minutes"], [60, "1 hour"], [120, "2 hours"],
  [180, "3 hours"], [360, "6 hours"], [720, "12 hours"], [1440, "24 hours"],
];

export default function BrowsePanel({ system, onJobStarted }) {
  const [cameras, setCameras] = useState([]);
  const [camera, setCamera] = useState("");
  const [days, setDays] = useState([]);
  const [day, setDay] = useState("");
  const [data, setData] = useState(null);
  const [hourFilter, setHourFilter] = useState(null);
  const [preview, setPreview] = useState(null);
  const [startTime, setStartTime] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function loadCameras() {
    setError(null);
    try {
      const list = await api.cameras();
      setCameras(list);
      if (!camera && list.length) setCamera(list[0]);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    if (system?.b2_configured) loadCameras();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [system?.b2_configured]);

  useEffect(() => {
    if (!camera) return;
    setDays([]);
    setDay("");
    setData(null);
    api.days(camera)
      .then((list) => {
        setDays(list);
        if (list.length) setDay(list[0]);
      })
      .catch((e) => setError(e.message));
  }, [camera]);

  useEffect(() => {
    if (!camera || !day) return;
    setLoading(true);
    setHourFilter(null);
    setPreview(null);
    api.clips(camera, day)
      .then((result) => {
        setData(result);
        if (result.clips.length && !startTime) setStartTime(timeOnly(result.clips[0].start_time));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, day]);

  async function startDownload() {
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      await api.startDownload({
        camera,
        start: `${day}T${startTime.length === 5 ? `${startTime}:00` : startTime}`,
        duration_seconds: Number(minutes) * 60,
      });
      setMessage("Download job started. See the Jobs tab.");
      onJobStarted?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }

  if (system && !system.b2_configured) {
    return (
      <Card title="Browse clips">
        <p className="mt-3 text-sm text-slate-600">Enter your Backblaze bucket and key in Settings first.</p>
      </Card>
    );
  }

  const visibleClips = (data?.clips ?? []).filter(
    (clip) => hourFilter == null || Number(clip.end_time.slice(11, 13)) === hourFilter,
  );

  return (
    <div className="space-y-4">
      <Card
        title="Browse clips"
        subtitle="Pick a camera and a day. Each clip is one 3-minute recording as uploaded by the Pi."
        right={<Button icon={RefreshCw} variant="secondary" onClick={loadCameras}>Refresh</Button>}
      >
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <Field label="Camera">
            <select className={inputClass} value={camera} onChange={(e) => setCamera(e.target.value)}>
              {cameras.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </Field>
          <Field label="Day" hint={days.length ? `${days.length} day(s) in the bucket` : "No days found"}>
            <select className={inputClass} value={day} onChange={(e) => setDay(e.target.value)}>
              {days.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
          <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
            {loading ? "Loading..." : data ? (
              <>
                <div className="text-2xl font-semibold text-slate-900">{data.count} clips</div>
                <div>{formatBytes(data.bytes)} on this day</div>
              </>
            ) : "Choose a day"}
          </div>
        </div>

        {data && data.hours.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-2">
            <button type="button" onClick={() => setHourFilter(null)} className={`rounded-full px-3 py-1 text-xs font-semibold ${hourFilter == null ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"}`}>All hours</button>
            {data.hours.map((h) => (
              <button key={h.hour} type="button" onClick={() => setHourFilter(h.hour)} className={`rounded-full px-3 py-1 text-xs font-semibold ${hourFilter === h.hour ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"}`}>
                {String(h.hour).padStart(2, "0")}:00 <span className="text-slate-400">({h.count})</span>
              </button>
            ))}
          </div>
        )}
        <Message error={error} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Download a window" subtitle="Clips are joined into one file in the output folder." className="lg:col-span-2">
          <div className="mt-5 space-y-4">
            <Field label="Start time" hint={`${camera || "camera"} on ${day || "day"}. Click a clip to use its start.`}>
              <input type="time" step="1" className={inputClass} value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            </Field>
            <Field label="Duration">
              <select className={inputClass} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {DURATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Button icon={Download} onClick={startDownload} busy={pending} disabled={!camera || !day || !startTime || !system?.ffmpeg_available}>
              Download and join
            </Button>
            {!system?.ffmpeg_available && <p className="text-xs text-red-700">ffmpeg is needed to join clips. See Settings.</p>}
            <Message message={message} />
          </div>
        </Card>

        <Card title={hourFilter == null ? "Clips" : `Clips at ${String(hourFilter).padStart(2, "0")}:00`} className="lg:col-span-3">
          {preview && (
            <div className="mt-4 rounded-2xl bg-slate-950 p-3">
              <div className="flex items-center justify-between text-xs text-slate-300">
                <span className="font-mono">{preview.filename}</span>
                <button type="button" onClick={() => setPreview(null)} className="flex items-center gap-1"><X size={14} /> close</button>
              </div>
              <video key={preview.key} controls autoPlay className="mt-2 w-full rounded-xl" src={api.previewUrl(preview.key)} />
              <p className="mt-2 text-xs text-slate-400">The clip is downloaded to a local cache first, so the first play of a clip takes a few seconds.</p>
            </div>
          )}
          <div className="mt-4 max-h-[520px] overflow-y-auto">
            {visibleClips.length === 0 && <p className="text-sm text-slate-500">No clips.</p>}
            <table className="w-full text-sm">
              <tbody>
                {visibleClips.map((clip) => (
                  <tr key={clip.key} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs text-slate-700">
                      {timeOnly(clip.start_time)} – {timeOnly(clip.end_time)}
                    </td>
                    <td className="py-2 text-xs text-slate-500">{formatBytes(clip.size)}</td>
                    <td className="py-2"><Badge tone={clip.extension === "mp4" ? "blue" : "slate"}>{clip.extension}</Badge></td>
                    <td className="py-2 text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="subtle" className="px-3 py-1.5 text-xs" onClick={() => setStartTime(timeOnly(clip.start_time))}>Start here</Button>
                        <Button variant="subtle" icon={Play} className="px-3 py-1.5 text-xs" onClick={() => setPreview(clip)}>Preview</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
