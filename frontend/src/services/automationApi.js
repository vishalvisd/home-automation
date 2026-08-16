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

  throw new Error(message);
}


export async function getAutomations() {
  const response = await fetch("/api/automations");
  return handleResponse(response);
}


export async function getAutomation(key) {
  const response = await fetch(`/api/automations/${key}`);
  return handleResponse(response);
}


export async function saveAutomation(key, source) {
  const response = await fetch(`/api/automations/${key}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source }),
  });

  return handleResponse(response);
}


export async function restoreAutomation(key) {
  const response = await fetch(
    `/api/automations/${key}/restore`,
    {
      method: "POST",
    },
  );

  return handleResponse(response);
}


export async function runAutomation(key) {
  const response = await fetch(
    `/api/automations/${key}/run`,
    {
      method: "POST",
    },
  );

  return handleResponse(response);
}