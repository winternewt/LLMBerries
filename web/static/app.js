// Hash router bootstrap. Views arrive with the replay browser; for now the
// archive proves the wire works end to end.

const view = document.getElementById("view");

document.getElementById("crt-toggle").addEventListener("click", () => {
  document.body.classList.toggle("crt");
});

async function showRuns() {
  const res = await fetch("/api/runs");
  const data = await res.json();
  if (!data.runs.length) {
    view.innerHTML = `<div class="panel"><pre class="dim">┌─ TAPE ARCHIVE ─┐\n│ no recordings │\n└───────────────┘</pre></div>`;
    return;
  }
  const rows = data.runs
    .map(
      (r) => `<tr class="row"><td>${r.stamp}</td><td>${r.complete ? (r.outcome ?? "") : '<span class="badge alert">INCOMPLETE</span>'}</td><td>${r.hours_played ?? ""}</td><td>${r.agent_count ?? ""}</td><td>${r.framing ?? ""}</td><td>${(r.providers ?? []).join(", ")}</td></tr>`
    )
    .join("");
  view.innerHTML = `<div class="panel"><pre class="panel-title">┌─ TAPE ARCHIVE ─┐</pre><table><tr><th>stamp</th><th>outcome</th><th>hours</th><th>seats</th><th>framing</th><th>minds</th></table></div>`;
  view.querySelector("table").insertAdjacentHTML("beforeend", rows);
}

function route() {
  const hash = location.hash || "#/runs";
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.getAttribute("href") === hash);
  }
  if (hash.startsWith("#/runs")) return showRuns();
  view.innerHTML = `<div class="panel"><pre class="dim">not wired yet</pre></div>`;
}

window.addEventListener("hashchange", route);
route();
