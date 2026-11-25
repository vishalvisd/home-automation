import { buildLiveStreamUrl } from "./liveUrl";


async function handleResponse(response) {
  if (response.ok) {
    return response.json();
  }

  let message = `HTTP ${response.status}`;

  try {
    const body = await response.json();
    message = body.detail || message;
  } catch {
    // Response did not contain JSON.
  }

  throw new Error(message);
}


export async function getLiveStatus() {
  const response = await fetch("/api/cameras/live");
  return handleResponse(response);
}


export async function syncLiveView() {
  const response = await fetch("/api/cameras/live/sync", {
    method: "POST",
  });

  return handleResponse(response);
}


// Where the browser connects for video; the rules are in liveUrl.js.
// During `npm run dev` the page is served from the Mac, so the host can
// be overridden with VITE_LIVE_HOST.
export function liveStreamUrl(port, streamKey) {
  return buildLiveStreamUrl(
    window.location,
    port,
    streamKey,
    import.meta.env.VITE_LIVE_HOST,
  );
}
