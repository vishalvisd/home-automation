async function readError(response) {
  try {
    const body = await response.json();
    return body.detail || JSON.stringify(body);
  } catch {
    return `HTTP ${response.status}`;
  }
}

export async function getBackendHealth() {
  const response = await fetch("/health");

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json();
}

export async function sendRelayCommand(relayKey, command) {
  const response = await fetch(
    `/api/relays/${relayKey}/${command}`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json();
}

export async function getWateringStatus() {
  const response = await fetch("/api/watering/status");

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json();
}

export async function startWatering() {
  const response = await fetch("/api/watering/start", {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json();
}

export async function stopWatering() {
  const response = await fetch("/api/watering/stop", {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json();
}