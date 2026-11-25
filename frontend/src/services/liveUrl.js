// Where the browser connects for live video. Kept apart from liveApi.js
// and free of anything browser-only, so tests/check_live_url.mjs can
// run it with plain node.
//
// At home the page is plain http on port 8000 and go2rtc answers on its
// own port of the same host.
//
// From the internet the page arrives over https through Tailscale
// Funnel. A browser refuses a plain connection from an https page, and
// go2rtc's port is not open to the internet. So the video goes to the
// page's own address, where the funnel hands /api/ws to go2rtc
// (scripts/install_tailscale.sh).
//
// pageLocation is window.location: { protocol, hostname, origin }.
// hostOverride is VITE_LIVE_HOST, used only by `npm run dev` on the Mac.
export function buildLiveStreamUrl(pageLocation, port, streamKey, hostOverride) {
  const path = `/api/ws?src=${encodeURIComponent(streamKey)}`;

  if (hostOverride) {
    return `http://${hostOverride}:${port}${path}`;
  }

  if (pageLocation.protocol === "https:") {
    return `${pageLocation.origin}${path}`;
  }

  return `http://${pageLocation.hostname}:${port}${path}`;
}
