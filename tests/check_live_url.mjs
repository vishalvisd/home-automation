// Checks the address the live view player connects to, at home and
// through Tailscale Funnel (frontend/src/services/liveUrl.js). Also
// checks what go2rtc's player then turns it into (ws or wss), with the
// same rule as the `set src` in frontend/src/vendor/video-rtc.js.
// Runs on the Mac, no Pi needed.
//
//   node tests/check_live_url.mjs

import { buildLiveStreamUrl } from "../frontend/src/services/liveUrl.js";

let failures = 0;

// The rule video-rtc.js applies to an address that starts with "http".
function asPlayerOpensIt(url) {
  return url.startsWith("http") ? "ws" + url.substring(4) : url;
}

function check(name, pageLocation, port, key, override, expected) {
  const got = asPlayerOpensIt(
    buildLiveStreamUrl(pageLocation, port, key, override),
  );

  if (got === expected) {
    console.log(`ok    ${name}`);
  } else {
    failures += 1;
    console.log(`FAIL  ${name}\n      got      ${got}\n      expected ${expected}`);
  }
}

const home = {
  protocol: "http:",
  hostname: "192.168.1.31",
  origin: "http://192.168.1.31:8000",
};

const funnel = {
  protocol: "https:",
  hostname: "visd-ha.example.ts.net",
  origin: "https://visd-ha.example.ts.net",
};

const macPreview = {
  protocol: "http:",
  hostname: "localhost",
  origin: "http://localhost:5180",
};

check(
  "at home: go2rtc's own port, plain",
  home, 1984, "cam1", undefined,
  "ws://192.168.1.31:1984/api/ws?src=cam1",
);

check(
  "at home: sub stream",
  home, 1984, "cam2_sub", undefined,
  "ws://192.168.1.31:1984/api/ws?src=cam2_sub",
);

check(
  "through the funnel: the page's own address, encrypted, no port",
  funnel, 1984, "cam1", undefined,
  "wss://visd-ha.example.ts.net/api/ws?src=cam1",
);

check(
  "through the funnel: sub stream",
  funnel, 1984, "cam3_sub", undefined,
  "wss://visd-ha.example.ts.net/api/ws?src=cam3_sub",
);

check(
  "Mac preview: the override wins",
  macPreview, 1984, "cam1", "192.168.1.31",
  "ws://192.168.1.31:1984/api/ws?src=cam1",
);

check(
  "a stream name is escaped",
  home, 1984, "cam 1&x", undefined,
  "ws://192.168.1.31:1984/api/ws?src=cam%201%26x",
);

if (failures > 0) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}

console.log("\nall checks passed");
