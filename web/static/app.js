// Hash router and views. The game view is one shared renderer: the replay
// browser drives it from the archive; the live view (later) will drive it from
// the event stream.

import { api } from "./api.js";
import { esc, messageFlow, panel, ring, timeline, turnBlock } from "./render.js";

const view = document.getElementById("view");
let teardown = null; // the active view's cleanup (key handlers, timers)

document.getElementById("crt-toggle").addEventListener("click", () => {
  document.body.classList.toggle("crt");
});

function fail(err) {
  view.innerHTML = panel("NO SIGNAL", `<pre class="alert">${esc(err.message ?? err)}</pre>`);
}

// ---------------------------------------------------------------- tape archive

async function showRuns() {
  const data = await api.runs();
  if (!data.runs.length) {
    view.innerHTML = panel("TAPE ARCHIVE", `<pre class="dim">no recordings — play one:
  uv run python main.py --scripted --agents 5</pre>`);
    return;
  }
  const rows = data.runs
    .map((r) => {
      const outcome = r.complete
        ? `${esc(r.outcome ?? "")}${r.winner ? ` <span class="bright">${esc(r.winner)}</span>` : ""}`
        : `<span class="badge alert">INCOMPLETE</span>`;
      const badges = r.has_story ? ` <span class="badge">STORY</span>` : "";
      return `<tr class="row" data-stamp="${esc(r.stamp)}"><td>${esc(r.stamp)}</td>` +
        `<td>${outcome}</td><td>${r.hours_played ?? ""}</td><td>${r.agent_count ?? ""}</td>` +
        `<td>${esc(r.framing ?? "")}</td><td>${r.death_count ?? ""}</td>` +
        `<td>${(r.providers ?? []).map(esc).join(", ")}${badges}</td></tr>`;
    })
    .join("");
  view.innerHTML = panel(
    "TAPE ARCHIVE",
    `<table><tr><th>stamp</th><th>outcome</th><th>hours</th><th>seats</th>` +
      `<th>framing</th><th>deaths</th><th>minds</th></tr>${rows}</table>`
  );
  for (const row of view.querySelectorAll("tr.row")) {
    row.addEventListener("click", () => {
      location.hash = `#/run/${row.dataset.stamp}`;
    });
  }
}

// ------------------------------------------------------------------- game view

// Shared by replay and live: given a chronicle-shaped record, a way to fetch the
// world at an hour, and a cursor, draw everything.
export function drawGame(root, { record, state, hour, lastHour, maxHunger, statusLine }) {
  const summaries = {};
  const namesById = {};
  for (const agent of record?.agents ?? []) {
    summaries[agent.agent_id] = agent;
    namesById[agent.agent_id] = agent.name;
  }
  const deathHours = new Set((record?.deaths ?? []).map((d) => d.hour));
  const hourTurns = (record?.turns ?? []).filter((t) => t.hour === hour && t.kind === "action");
  const reflections = (record?.turns ?? []).filter((t) => t.kind === "reflection");
  const hourUnheard = (record?.unheard ?? []).filter((u) => u.hour === hour);

  const parts = [];
  if (statusLine) parts.push(panel("SIGNAL", statusLine));
  parts.push(panel("THE RING", ring(state, summaries, maxHunger)));
  parts.push(panel("TIMELINE", timeline(lastHour, hour, deathHours)));
  parts.push(
    panel(
      `HOUR ${String(hour).padStart(3, "0")}`,
      hourTurns.length
        ? hourTurns.map(turnBlock).join("")
        : `<div class="dim">every body within reach was asleep, or past acting</div>`
    )
  );
  parts.push(panel("WORDS ON THE AIR", messageFlow(hourTurns, hourUnheard, state.agents.length, namesById)));
  if (hour === lastHour && reflections.length) {
    parts.push(panel("LOOKING BACK", reflections.map(turnBlock).join("")));
  }
  if (hour === lastHour && record?.outcome) {
    const ending = record.winner
      ? `${esc(record.outcome)} — <span class="bright">${esc(record.winner)}</span>`
      : esc(record.outcome);
    parts.push(panel("HOW IT ENDED", `<div>${ending} · ${record.berries_left?.toFixed?.(1) ?? record.berries_left} berries left</div>`));
  }
  root.innerHTML = parts.join("");
}

async function showRun(stamp) {
  const [detail, meta] = await Promise.all([api.run(stamp), api.meta()]);
  if (!detail.complete && !detail.artifacts.includes("replay.json")) {
    view.innerHTML = panel(esc(stamp), `<pre class="alert">this run crashed before it could leave a replay</pre>`);
    return;
  }
  const record = detail.chronicle;
  const states = new Map();
  let hour = 0;
  let lastHour = 0;

  async function stateAt(h) {
    if (!states.has(h)) states.set(h, await api.state(stamp, h));
    return states.get(h);
  }

  async function draw() {
    const state = await stateAt(hour);
    lastHour = state.last_hour;
    drawGame(view, {
      record,
      state,
      hour,
      lastHour,
      maxHunger: meta.max_hunger,
      statusLine: `<div><span class="bright">${esc(stamp)}</span> · seed ${detail.seed} · framing ${esc(record?.framing ?? "?")} · <a href="#/runs">back to the archive</a></div>`,
    });
    for (const cell of view.querySelectorAll("#timeline .cell")) {
      cell.addEventListener("click", () => {
        hour = Number(cell.dataset.hour);
        draw();
      });
    }
  }

  function onKey(event) {
    if (event.key === "ArrowRight") hour = Math.min(lastHour, hour + 1);
    else if (event.key === "ArrowLeft") hour = Math.max(0, hour - 1);
    else if (event.key === "Home") hour = 0;
    else if (event.key === "End") hour = lastHour;
    else return;
    event.preventDefault();
    draw();
  }
  window.addEventListener("keydown", onKey);
  teardown = () => window.removeEventListener("keydown", onKey);

  await draw();
}

// ---------------------------------------------------------------------- router

const routes = [
  { pattern: /^#\/runs$/, show: () => showRuns() },
  { pattern: /^#\/run\/([0-9TZ-]+)$/, show: (m) => showRun(m[1]) },
  { pattern: /^#\/live$/, show: () => Promise.resolve(fail(new Error("the live wire is not strung yet"))) },
  { pattern: /^#\/launch$/, show: () => Promise.resolve(fail(new Error("the launch desk is not built yet"))) },
];

function route() {
  teardown?.();
  teardown = null;
  const hash = location.hash || "#/runs";
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", hash.startsWith(a.getAttribute("href")));
  }
  const match = routes.find((r) => r.pattern.exec(hash));
  if (!match) return fail(new Error(`no view at ${hash}`));
  match.show(match.pattern.exec(hash)).catch(fail);
}

window.addEventListener("hashchange", route);
route();
