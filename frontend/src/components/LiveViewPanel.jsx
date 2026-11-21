import { useEffect, useRef, useState } from "react";
import { LoaderCircle, RefreshCw, Video } from "lucide-react";

import {
  getLiveStatus,
  liveStreamUrl,
  syncLiveView,
} from "../services/liveApi";
import { VideoRTC } from "../vendor/video-rtc";


// go2rtc's player is a web component. Register it once.
if (!customElements.get("video-rtc")) {
  customElements.define("video-rtc", VideoRTC);
}

const SELECTION_STORAGE_KEY = "liveViewSelection";
const QUALITY_STORAGE_KEY = "liveViewQuality";

// WebRTC gives the lowest delay. MSE is the fallback for browsers or
// networks where WebRTC does not connect.
const PLAYER_MODE = "webrtc,mse";


function loadSelection() {
  try {
    const stored = localStorage.getItem(SELECTION_STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}


function saveSelection(keys) {
  try {
    localStorage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(keys));
  } catch {
    // Browser storage unavailable; the selection just is not remembered.
  }
}


function loadQuality() {
  try {
    return localStorage.getItem(QUALITY_STORAGE_KEY) === "sub" ? "sub" : "main";
  } catch {
    return "main";
  }
}


function saveQuality(quality) {
  try {
    localStorage.setItem(QUALITY_STORAGE_KEY, quality);
  } catch {
    // Not remembered, that is all.
  }
}


function LivePlayer({ streamKey, port }) {
  const holder = useRef(null);

  useEffect(() => {
    const player = document.createElement("video-rtc");
    player.mode = PLAYER_MODE;
    player.style.display = "block";
    player.style.width = "100%";
    player.style.aspectRatio = "16 / 9";
    player.style.background = "black";

    holder.current.appendChild(player);

    // Setting src starts the connection once the element is in the DOM.
    player.src = liveStreamUrl(port, streamKey);

    return () => {
      player.remove();
    };
  }, [streamKey, port]);

  return <div ref={holder} className="overflow-hidden rounded-xl bg-black" />;
}


export default function LiveViewPanel({ active }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(() => loadSelection());
  const [quality, setQuality] = useState(() => loadQuality());
  const [syncing, setSyncing] = useState(false);

  function chooseQuality(value) {
    setQuality(value);
    saveQuality(value);
  }

  async function refresh() {
    try {
      setStatus(await getLiveStatus());
      setError(null);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function resync() {
    setSyncing(true);

    try {
      setStatus(await syncLiveView());
      setError(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSyncing(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const cameras = (status?.cameras ?? []).filter(
    (camera) => camera.live_source !== "none",
  );

  // First visit: everything ticked. Afterwards the browser remembers.
  const selectedKeys =
    selected ?? cameras.map((camera) => camera.key);

  function toggle(key) {
    const next = selectedKeys.includes(key)
      ? selectedKeys.filter((item) => item !== key)
      : [...selectedKeys, key];

    setSelected(next);
    saveSelection(next);
  }

  const playing = cameras.filter((camera) =>
    selectedKeys.includes(camera.key),
  );

  const gridClass =
    playing.length <= 1
      ? "grid-cols-1"
      : playing.length <= 4
        ? "grid-cols-1 md:grid-cols-2"
        : "grid-cols-1 md:grid-cols-2 xl:grid-cols-3";

  const ready = status?.installed && status?.running;

  return (
    <section className="mt-8 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Video size={20} />
            <h2 className="text-lg font-semibold text-slate-950">
              Live View
            </h2>
          </div>

          <p className="mt-2 text-sm text-slate-600">
            Streams come straight from the cameras through go2rtc on
            the Pi, with no re-encoding. Tick the cameras to watch.
            Main is what the archive disk records; Sub is what goes to
            the cloud.
          </p>

          <div className="mt-3 inline-flex rounded-xl border border-slate-300 bg-white p-1 text-sm font-semibold">
            {[
              ["main", "Main stream"],
              ["sub", "Sub stream"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => chooseQuality(value)}
                className={`rounded-lg px-3 py-1.5 ${
                  quality === value
                    ? "bg-slate-950 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-300 bg-white"
            aria-label="Refresh status"
          >
            <RefreshCw size={16} />
          </button>

          <button
            type="button"
            onClick={resync}
            disabled={syncing}
            className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
          >
            {syncing ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : null}
            Resync go2rtc
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {status && !status.installed && (
        <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          go2rtc is not installed on the Pi. Run{" "}
          <code>bash scripts/install_go2rtc.sh</code> on the Pi once,
          then press Resync.
        </div>
      )}

      {status && status.installed && !status.running && (
        <div className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          go2rtc is installed but not answering on port {status.port}.
          Check <code>sudo systemctl status go2rtc</code> on the Pi.
        </div>
      )}

      {status?.last_error && (
        <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
          {status.last_error}
        </div>
      )}

      {status && cameras.length === 0 && (
        <p className="mt-4 text-sm text-slate-600">
          No RTSP cameras configured. Live view works for RTSP cameras
          only.
        </p>
      )}

      {cameras.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-3">
          {cameras.map((camera) => (
            <label
              key={camera.key}
              className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm"
            >
              <input
                type="checkbox"
                checked={selectedKeys.includes(camera.key)}
                onChange={() => toggle(camera.key)}
              />
              <span className="font-medium text-slate-900">
                {camera.name}
              </span>
              <span className="text-xs text-slate-500">
                {camera.sub_available ? "main + sub" : "main only"}
                {camera.loaded ? "" : " · not loaded"}
              </span>
            </label>
          ))}
        </div>
      )}

      {ready && active && playing.length > 0 && (
        <div className={`mt-5 grid gap-4 ${gridClass}`}>
          {playing.map((camera) => {
            const useSub = quality === "sub" && camera.sub_available;
            const streamKey = useSub ? `${camera.key}_sub` : camera.key;

            return (
              <div key={streamKey}>
                <LivePlayer streamKey={streamKey} port={status.port} />
                <p className="mt-2 text-sm font-medium text-slate-800">
                  {camera.name}
                  <span className="ml-2 text-xs font-normal text-slate-500">
                    {useSub
                      ? "sub stream"
                      : quality === "sub"
                        ? "main stream (no sub stream set)"
                        : "main stream"}
                  </span>
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
