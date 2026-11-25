// The automation scripts are guarded by a passphrase, checked by the
// backend on every request. It is kept here in memory only: reloading
// the page forgets it, and it is asked for again.
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
    "X-Automations-Passphrase": encodeURIComponent(passphrase ?? ""),
  };
}


async function handleResponse(response) {
  if (response.ok) {
    return response.json();
  }

  let message = response.statusText;

  try {
    const body = await response.json();
    message = body.detail || message;
  } catch {
    // Response did not contain JSON.
  }

  const error = new Error(message);
  // 401: wrong passphrase. 403: none has been set yet.
  error.status = response.status;

  throw error;
}


// Open to anyone: { set: true } once a passphrase exists.
export async function getPassphraseState() {
  const response = await fetch("/api/automations/passphrase");
  return handleResponse(response);
}


// First time only. The backend refuses when one is already set.
export async function createPassphrase(value) {
  const response = await fetch("/api/automations/passphrase", {
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
    const response = await fetch("/api/automations/passphrase/check", {
      method: "POST",
      headers: guardHeaders(),
    });

    return await handleResponse(response);
  } catch (error) {
    passphrase = null;
    throw error;
  }
}


export async function getAutomations() {
  const response = await fetch("/api/automations", {
    headers: guardHeaders(),
  });

  return handleResponse(response);
}


export async function getAutomation(key) {
  const response = await fetch(`/api/automations/${key}`, {
    headers: guardHeaders(),
  });

  return handleResponse(response);
}


export async function saveAutomation(key, source) {
  const response = await fetch(`/api/automations/${key}`, {
    method: "PUT",
    headers: guardHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({ source }),
  });

  return handleResponse(response);
}


export async function restoreAutomation(key) {
  const response = await fetch(
    `/api/automations/${key}/restore`,
    {
      method: "POST",
      headers: guardHeaders(),
    },
  );

  return handleResponse(response);
}


export async function runAutomation(key) {
  const response = await fetch(
    `/api/automations/${key}/run`,
    {
      method: "POST",
      headers: guardHeaders(),
    },
  );

  return handleResponse(response);
}
