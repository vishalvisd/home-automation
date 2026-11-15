async function handleResponse(response) {
  if (response.ok) {
    return response.json();
  }

  let message = `HTTP ${response.status}`;

  try {
    const body = await response.json();

    if (Array.isArray(body.detail)) {
      // FastAPI validation errors arrive as a list.
      message = body.detail
        .map((item) => item.msg)
        .join(" ");
    } else {
      message = body.detail || message;
    }
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


export async function getPresetStatus() {
  const response = await fetch(
    "/api/cameras/preset/status",
  );

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

export async function getBackblazeAccounts() {
  const response = await fetch(
    "/api/cameras/backblaze/accounts",
  );

  return handleResponse(response);
}


export async function saveBackblazeAccounts(accounts) {
  const response = await fetch(
    "/api/cameras/backblaze/accounts",
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ accounts }),
    },
  );

  return handleResponse(response);
}


export async function getBackblazeRotation() {
  const response = await fetch(
    "/api/cameras/backblaze/rotation",
  );

  return handleResponse(response);
}


export async function testBackblazeAccount(account) {
  const response = await fetch(
    "/api/cameras/backblaze/accounts/test",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(account),
    },
  );

  return handleResponse(response);
}
