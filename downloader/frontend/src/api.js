async function handle(response) {
  if (response.ok) {
    return response.json();
  }

  let message = `HTTP ${response.status}`;

  try {
    const body = await response.json();
    if (Array.isArray(body.detail)) {
      message = body.detail.map((item) => item.msg).join(" ");
    } else {
      message = body.detail || message;
    }
  } catch {
    // no JSON body
  }

  throw new Error(message);
}

const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  system: () => fetch("/api/system").then(handle),

  getSettings: () => fetch("/api/settings").then(handle),
  saveSettings: (changes) => fetch("/api/settings", json("PUT", changes)).then(handle),
  testConnection: () => fetch("/api/settings/test", { method: "POST" }).then(handle),

  cameras: (source = "cloud") => fetch(`/api/browse/cameras?source=${source}`).then(handle),
  days: (camera, source = "cloud") => fetch(`/api/browse/days?camera=${camera}&source=${source}`).then(handle),
  clips: (camera, day, source = "cloud") =>
    fetch(`/api/browse/clips?camera=${camera}&day=${day}&source=${source}`).then(handle),
  previewUrl: (key, account = "", source = "cloud") =>
    `/api/preview?key=${encodeURIComponent(key)}&account=${encodeURIComponent(account)}&source=${source}`,

  jobs: () => fetch("/api/jobs").then(handle),
  startDownload: (request) => fetch("/api/jobs/download", json("POST", request)).then(handle),
  startTimelapse: (request) => fetch("/api/jobs/timelapse", json("POST", request)).then(handle),
  cancelJob: (id) => fetch(`/api/jobs/${id}/cancel`, { method: "POST" }).then(handle),
  deleteJob: (id) => fetch(`/api/jobs/${id}`, { method: "DELETE" }).then(handle),

  library: () => fetch("/api/library").then(handle),
  fileUrl: (path) => `/api/library/file?path=${encodeURIComponent(path)}`,
  fileInfo: (path) => fetch(`/api/library/info?path=${encodeURIComponent(path)}`).then(handle),
  openFolder: (path) => fetch("/api/library/open", json("POST", { path })).then(handle),
  deleteFile: (path) => fetch(`/api/library?path=${encodeURIComponent(path)}`, { method: "DELETE" }).then(handle),
};

export function formatBytes(size) {
  if (size == null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatDuration(seconds) {
  if (seconds == null) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}h ${m}m ${s}s` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function timeOnly(iso) {
  return iso ? iso.slice(11, 19) : "";
}
