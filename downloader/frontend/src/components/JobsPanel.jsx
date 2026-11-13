import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, FolderOpen, Trash2, XCircle } from "lucide-react";

import { api, formatBytes, formatDuration } from "../api";
import { Badge, Button, Card, Message, Progress } from "./ui";

const TONES = { queued: "slate", running: "blue", done: "green", failed: "red", cancelled: "amber" };

export default function JobsPanel() {
  const [jobs, setJobs] = useState([]);
  const [open, setOpen] = useState({});
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      setJobs(await api.jobs());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 2000);
    return () => window.clearInterval(interval);
  }, []);

  async function act(fn) {
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <Card title="Jobs" subtitle="Downloads, time-lapses and archive runs. One job runs at a time.">
      <Message error={error} />
      <div className="mt-4 space-y-3">
        {jobs.length === 0 && <p className="text-sm text-slate-500">No jobs yet.</p>}
        {jobs.map((job) => (
          <div key={job.id} className="rounded-2xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="font-semibold text-slate-900">{job.title}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {job.kind} · created {job.created_at?.slice(0, 16).replace("T", " ")}
                  {job.finished_at && ` · finished ${job.finished_at.slice(11, 16)}`}
                </div>
              </div>
              <Badge tone={TONES[job.status] ?? "slate"}>{job.status}</Badge>
            </div>

            {(job.status === "running" || job.status === "queued") && (
              <div className="mt-3">
                <Progress value={job.progress} />
                <div className="mt-1 text-xs text-slate-600">{job.message} · {Math.round(job.progress * 100)}%</div>
              </div>
            )}

            {job.status === "failed" && <div className="mt-3 rounded-xl bg-red-50 p-3 text-xs text-red-700">{job.error}</div>}

            {job.status === "done" && job.result?.output_path && (
              <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
                <div className="break-all font-mono">{job.result.output_path}</div>
                <div className="mt-1 text-slate-500">
                  {job.result.clips != null && `${job.result.clips} clips · `}
                  {formatBytes(job.result.bytes)}
                  {job.result.duration_seconds != null && ` · ${formatDuration(job.result.duration_seconds)}`}
                  {job.result.encoder && ` · encoder ${job.result.encoder}`}
                </div>
              </div>
            )}

            {job.status === "done" && job.kind === "archive" && (
              <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
                {job.result.clips_in_bucket} clips in bucket ({formatBytes(job.result.bytes_in_bucket)}) mirrored to{" "}
                <span className="font-mono">{job.result.archive_directory}</span>
                {job.result.pruned_files > 0 && ` · ${job.result.pruned_files} old files pruned`}
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {(job.status === "running" || job.status === "queued") && (
                <Button variant="secondary" icon={XCircle} className="px-3 py-1.5 text-xs" onClick={() => act(() => api.cancelJob(job.id))}>Cancel</Button>
              )}
              {job.status === "done" && job.result?.output_path && (
                <Button variant="secondary" icon={FolderOpen} className="px-3 py-1.5 text-xs" onClick={() => act(() => api.openFolder(job.result.output_path))}>Show in folder</Button>
              )}
              {job.status !== "running" && (
                <Button variant="subtle" icon={Trash2} className="px-3 py-1.5 text-xs" onClick={() => act(() => api.deleteJob(job.id))}>Remove</Button>
              )}
              {job.log?.length > 0 && (
                <Button variant="subtle" icon={open[job.id] ? ChevronUp : ChevronDown} className="px-3 py-1.5 text-xs" onClick={() => setOpen((o) => ({ ...o, [job.id]: !o[job.id] }))}>
                  Log ({job.log.length})
                </Button>
              )}
            </div>

            {open[job.id] && (
              <pre className="mt-3 max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-200">{job.log.join("\n")}</pre>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
