// Thin fetch wrappers. Every call returns parsed JSON or throws with the
// server's detail line, which the views print rather than swallow.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON — keep the status */
    }
    throw new Error(detail);
  }
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? res.status));
  }
  return data;
}

export const api = {
  meta: () => getJSON("/api/meta"),
  runs: () => getJSON("/api/runs"),
  run: (stamp) => getJSON(`/api/runs/${stamp}`),
  state: (stamp, hour) => getJSON(`/api/runs/${stamp}/state?hour=${hour}`),
  providers: (refresh) => getJSON(`/api/providers${refresh ? "?refresh=true" : ""}`),
  current: () => getJSON("/api/games/current"),
  currentState: () => getJSON("/api/games/current/state"),
  launch: (request) => postJSON("/api/games", request),
  stop: () => postJSON("/api/games/current/stop"),
};
