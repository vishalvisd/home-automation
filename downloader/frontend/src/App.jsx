import { useEffect, useState } from "react";
import { Film, FolderOpen, ListChecks, Settings as SettingsIcon } from "lucide-react";

import { api } from "./api";
import BrowsePanel from "./components/BrowsePanel";
import JobsPanel from "./components/JobsPanel";
import LibraryPanel from "./components/LibraryPanel";
import SettingsPanel from "./components/SettingsPanel";
import { Badge } from "./components/ui";

const TABS = [
  { key: "browse", label: "Browse", icon: Film },
  { key: "jobs", label: "Jobs", icon: ListChecks },
  { key: "library", label: "Library", icon: FolderOpen },
  { key: "settings", label: "Settings", icon: SettingsIcon },
];

export default function App() {
  const [tab, setTab] = useState("browse");
  const [system, setSystem] = useState(null);
  const [activeJobs, setActiveJobs] = useState(0);

  async function refreshSystem() {
    try {
      setSystem(await api.system());
    } catch {
      setSystem(null);
    }
  }

  useEffect(() => {
    refreshSystem();

    const interval = window.setInterval(async () => {
      try {
        const jobs = await api.jobs();
        setActiveJobs(jobs.filter((job) => job.status === "queued" || job.status === "running").length);
      } catch {
        // backend not reachable
      }
    }, 3000);

    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (system && !system.pi_configured) {
      setTab("settings");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [system?.pi_configured]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="rounded-3xl bg-slate-950 p-6 text-white">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">
              visdcam
            </div>
            <h1 className="mt-1 text-2xl font-semibold">CCTV Downloader</h1>
            <p className="mt-1 text-sm text-slate-300">
              Browse, download, join and time-lapse clips from the Backblaze accounts the Pi uploads to.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={system ? "green" : "red"}>{system ? "Backend online" : "Backend offline"}</Badge>
            {system && (
              <Badge tone={system.ffmpeg_available ? "green" : "red"}>
                {system.ffmpeg_available ? `ffmpeg ${system.ffmpeg_version ?? ""}` : "ffmpeg missing"}
              </Badge>
            )}
            {system && (
              <Badge tone={system.pi_configured ? "green" : "amber"}>
                {system.pi_configured ? `Pi ${system.pi_url}` : "Pi address not set"}
              </Badge>
            )}
          </div>
        </div>
      </header>

      <nav className="mt-4 flex gap-1 overflow-x-auto rounded-2xl bg-white p-1 shadow-sm">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 whitespace-nowrap rounded-xl px-4 py-2 text-sm font-semibold ${
              tab === key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            <Icon size={16} />
            {label}
            {key === "jobs" && activeJobs > 0 && (
              <span className="rounded-full bg-blue-600 px-2 py-0.5 text-xs text-white">{activeJobs}</span>
            )}
          </button>
        ))}
      </nav>

      <main className="mt-4 space-y-4">
        <div className={tab === "browse" ? "" : "hidden"}><BrowsePanel system={system} onJobStarted={() => setTab("jobs")} /></div>
        <div className={tab === "jobs" ? "" : "hidden"}><JobsPanel /></div>
        <div className={tab === "library" ? "" : "hidden"}><LibraryPanel system={system} onJobStarted={() => setTab("jobs")} /></div>
        <div className={tab === "settings" ? "" : "hidden"}><SettingsPanel system={system} onSaved={refreshSystem} /></div>
      </main>
    </div>
  );
}
