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

// ------------------------------------------------------------------- live view

async function showLive() {
  const [snapshot, meta] = await Promise.all([api.current(), api.meta()]);
  if (snapshot.phase === "idle") {
    view.innerHTML = panel(
      "LIVE",
      `<div class="dim">nothing is running — <a href="#/launch">open the launch desk</a></div>`
    );
    return;
  }

  // The record grows out of the stream: turns from the chronicler's side of the
  // feed, deaths and unheard words from the bus's side.
  const record = { agents: [], turns: [], deaths: [], unheard: [], outcome: null, winner: null };
  const seenAgents = new Set();
  let phase = snapshot.phase;
  let lastEventAt = Date.now();
  let lastEventLine = "listening…";
  let finishedStamp = null;
  let dirty = true;

  const source = new EventSource("/api/games/current/stream");
  source.addEventListener("turn", (message) => {
    const turn = JSON.parse(message.data);
    record.turns.push(turn);
    if (!seenAgents.has(turn.agent_id)) {
      seenAgents.add(turn.agent_id);
      record.agents.push({ agent_id: turn.agent_id, name: turn.agent_name, provider: turn.provider });
    }
    dirty = true;
  });
  source.addEventListener("event", (message) => {
    const event = JSON.parse(message.data);
    lastEventAt = Date.now();
    lastEventLine = event.message ?? event.event_type;
    if (event.event_type === "agent_died") {
      record.deaths.push({ hour: Math.floor(event.game_time), agent_id: event.agent_id });
      dirty = true;
    }
    if (event.event_type === "message_undelivered") {
      record.unheard.push({
        hour: Math.floor(event.game_time),
        speaker: event.data?.from_agent,
        listener: event.data?.to_agent,
        direction: event.data?.direction,
      });
      dirty = true;
    }
  });
  source.addEventListener("status", (message) => {
    const status = JSON.parse(message.data);
    phase = status.phase;
    record.outcome = status.outcome ?? null;
    finishedStamp = status.stamp ?? null;
    dirty = true;
    source.close();
  });
  source.onerror = () => {
    lastEventLine = "signal lost — retrying";
  };

  async function draw() {
    let state;
    try {
      state = await api.currentState();
    } catch {
      view.innerHTML = panel("LIVE", `<div class="dim">the world is being set up…</div>`);
      return;
    }
    const age = Math.round((Date.now() - lastEventAt) / 1000);
    const status =
      phase === "running"
        ? `<span class="ok">RUNNING</span> · HR ${state.hour} · ${esc(lastEventLine)}` +
          (age > 5 ? ` <span class="dim">(${age}s ago — a mind is taking its time)</span>` : "") +
          ` · <button id="stop-btn" type="button">[ STOP ]</button>`
        : `<span class="${phase === "failed" ? "alert" : "bright"}">${esc(phase.toUpperCase())}</span>` +
          (finishedStamp ? ` · <a href="#/run/${esc(finishedStamp)}">open the recording</a>` : "");
    drawGame(view, {
      record,
      state,
      hour: state.hour,
      lastHour: state.last_hour,
      maxHunger: meta.max_hunger,
      statusLine: `<div>${status}</div>`,
    });
    document.getElementById("stop-btn")?.addEventListener("click", async () => {
      await api.stop().catch(fail);
    });
  }

  const ticker = setInterval(() => {
    if (dirty || phase === "running") {
      dirty = false;
      draw().catch(() => {});
    }
    if (phase !== "running" && !dirty) clearInterval(ticker);
  }, 700);
  teardown = () => {
    clearInterval(ticker);
    source.close();
  };

  await draw();
}

// ----------------------------------------------------------------- launch desk

async function showLaunch() {
  const meta = await api.meta();
  const providerBoxes = meta.providers
    .map(
      (name) =>
        `<label><input type="checkbox" name="provider" value="${esc(name)}"> ${esc(name)}</label>`
    )
    .join(" ");
  const zombieOptions = ["<option value=''>none</option>"]
    .concat(meta.zombie_flavours.map((f) => `<option value="${esc(f)}">${esc(f)}</option>`))
    .join("");
  const framingOptions = meta.framings
    .map((f) => `<option value="${esc(f)}">${esc(f)}</option>`)
    .join("");

  view.innerHTML = panel(
    "LAUNCH DESK",
    `<form class="launch" id="launch-form">
      <label>seats</label><input type="number" name="agents" min="${meta.min_agents}" max="8" value="5">
      <label>scripted (no keys)</label><input type="checkbox" name="scripted" checked>
      <label>zombie in the last seat</label><select name="zombie">${zombieOptions}</select>
      <label>minds (unchecked = all)</label><div>${providerBoxes}</div>
      <label>framing</label><select name="framing">${framingOptions}</select>
      <label>hours at most</label><input type="number" name="max_hours" min="1" max="${meta.max_hours_default}" value="24">
      <label>seed (blank = drawn)</label><input type="number" name="seed">
      <label>pause between hours (s)</label><input type="number" name="hour_delay" min="0" max="10" step="0.5" value="1">
      <label>keep the recording</label><input type="checkbox" name="record" checked>
      <div></div><button type="submit">[ BEGIN ]</button>
    </form>
    <div id="launch-note" class="dim"></div>`
  );

  document.getElementById("launch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const chosen = [...form.querySelectorAll("input[name=provider]:checked")].map((b) => b.value);
    const request = {
      agents: Number(form.agents.value),
      scripted: form.scripted.checked,
      zombie: form.zombie.value || null,
      providers: chosen.length ? chosen : null,
      framing: form.framing.value,
      max_hours: Number(form.max_hours.value),
      seed: form.seed.value === "" ? null : Number(form.seed.value),
      hour_delay: Number(form.hour_delay.value),
      record: form.record.checked,
    };
    const note = document.getElementById("launch-note");
    try {
      const born = await api.launch(request);
      note.textContent = `running as ${born.stamp ?? "(unrecorded)"}, seed ${born.seed}`;
      location.hash = "#/live";
    } catch (err) {
      note.innerHTML = `<span class="alert">${esc(err.message)}</span>`;
    }
  });
}

// ---------------------------------------------------------------------- router

const routes = [
  { pattern: /^#\/runs$/, show: () => showRuns() },
  { pattern: /^#\/run\/([0-9TZ-]+)$/, show: (m) => showRun(m[1]) },
  { pattern: /^#\/live$/, show: () => showLive() },
  { pattern: /^#\/launch$/, show: () => showLaunch() },
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
