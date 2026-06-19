// Server-side only (imported exclusively from route handlers). Talks to the
// TaskPilot API and injects the API key from a server env var, so the secret
// never reaches the browser.
const API_URL = process.env.TASKPILOT_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.TASKPILOT_API_KEY ?? "";

export async function backendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
}
