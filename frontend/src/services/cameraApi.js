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


export async function getCameraSettings() {
  const response = await fetch("/api/cameras/settings");
  return handleResponse(response);
}


export async function saveCameraSettings(settings) {
  const response = await fetch("/api/cameras/settings", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  });

  return handleResponse(response);
}


export async function getRecordingStatus() {
  const response = await fetch(
    "/api/cameras/recording/status",
  );

  return handleResponse(response);
}


export async function startRecording() {
  const response = await fetch(
    "/api/cameras/recording/start",
    {
      method: "POST",
    },
  );

  return handleResponse(response);
}


export async function stopRecording() {
  const response = await fetch(
    "/api/cameras/recording/stop",
    {
      method: "POST",
    },
  );

  return handleResponse(response);
}

export async function getBackblazeCredentialsStatus() {
  const response = await fetch(
    "/api/cameras/backblaze/credentials",
  );

  return handleResponse(response);
}


export async function saveBackblazeCredentials(
  keyId,
  applicationKey,
) {
  const response = await fetch(
    "/api/cameras/backblaze/credentials",
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        key_id: keyId,
        application_key: applicationKey,
      }),
    },
  );

  return handleResponse(response);
}