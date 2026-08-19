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

export const api = {
  meta: () => getJSON("/api/meta"),
  runs: () => getJSON("/api/runs"),
  run: (stamp) => getJSON(`/api/runs/${stamp}`),
  state: (stamp, hour) => getJSON(`/api/runs/${stamp}/state?hour=${hour}`),
};
