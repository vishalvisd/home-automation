// Everything about the room microphones is guarded by a passphrase of
// its own, checked by the backend on every request. It is kept here in
// memory only: reloading the page forgets it, and it is asked for again.
let passphrase = null;


export function hasPassphrase() {
  return passphrase !== null;
}


export function forgetPassphrase() {
  passphrase = null;
}


function guardHeaders(extra = {}) {
  // Percent-encoded, because a header cannot carry every character.
  return {
    ...extra,
    "X-Mics-Passphrase": encodeURIComponent(passphrase ?? ""),
  };
}


async function failure(response) {
  let message = `HTTP ${response.status}`;

  try {
    const body = await response.json();

    if (Array.isArray(body.detail)) {
      // FastAPI validation errors arrive as a list.
      message = body.detail.map((item) => item.msg).join(" ");
    } else {
      message = body.detail || message;
    }
  } catch {
    // Response did not contain JSON.
  }

  const error = new Error(message);
  // 401: wrong passphrase. 403: none has been set yet.
  error.status = response.status;

  return error;
}


async function handleResponse(response) {
  if (response.ok) {
    return response.json();
  }

  throw await failure(response);
}


// Open to anyone: { set: true } once a passphrase exists.
export async function getPassphraseState() {
  const response = await fetch("/api/mics/passphrase");
  return handleResponse(response);
}


// First time only. The backend refuses when one is already set.
export async function createPassphrase(value) {
  const response = await fetch("/api/mics/passphrase", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ passphrase: value }),
  });

  const result = await handleResponse(response);
  passphrase = value;

  return result;
}


// Keeps the passphrase for this page if the backend accepts it.
export async function unlock(value) {
  passphrase = value;

  try {
    const response = await fetch("/api/mics/passphrase/check", {
      method: "POST",
      headers: guardHeaders(),
    });

    return await handleResponse(response);
  } catch (error) {
    passphrase = null;
    throw error;
  }
}


export async function getMicStatus() {
  const response = await fetch("/api/mics/status", {
    headers: guardHeaders(),
  });

  return handleResponse(response);
}


export async function getMicSettings() {
  const response = await fetch("/api/mics/settings", {
    headers: guardHeaders(),
  });

  return handleResponse(response);
}


// The settings that are not about one module.
export async function saveMicSettings(settings) {
  const response = await fetch("/api/mics/settings", {
    method: "PUT",
    headers: guardHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(settings),
  });

  return handleResponse(response);
}


// A module's room name, and whether it is switched on.
export async function saveMicModule(moduleId, { name, enabled }) {
  const response = await fetch(`/api/mics/modules/${moduleId}`, {
    method: "PUT",
    headers: guardHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({ name, enabled }),
  });

  return handleResponse(response);
}


export async function removeMicModule(moduleId) {
  const response = await fetch(`/api/mics/modules/${moduleId}`, {
    method: "DELETE",
    headers: guardHeaders(),
  });

  return handleResponse(response);
}


// The module's sound as it arrives, without end: raw samples, 16-bit,
// low byte first, mono, 16000 a second. Abort the signal to stop.
export async function openMicLive(moduleId, signal) {
  const response = await fetch(`/api/mics/modules/${moduleId}/live`, {
    headers: guardHeaders(),
    signal,
  });

  if (!response.ok) {
    throw await failure(response);
  }

  return response;
}


// The stored sound between two moments (seconds since 1970), as a
// file: { blob, name }.
export async function downloadMicSound(
  moduleId,
  { start, end, format, level },
) {
  const query = new URLSearchParams({
    start: String(start),
    end: String(end),
    format,
    level: level ? "true" : "false",
  });

  const response = await fetch(
    `/api/mics/modules/${moduleId}/download?${query}`,
    {
      headers: guardHeaders(),
    },
  );

  if (!response.ok) {
    throw await failure(response);
  }

  const named = /filename="([^"]+)"/.exec(
    response.headers.get("Content-Disposition") || "",
  );

  return {
    blob: await response.blob(),
    name: named ? named[1] : `microphone.${format}`,
  };
}
