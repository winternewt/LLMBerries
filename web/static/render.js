// Pure HTML builders. Everything that came out of a chronicle is escaped —
// reasoning traces and speech are arbitrary model output, not markup.

export function esc(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export const GLYPHS = { awake: "*", asleep: "~", dead: "☠", crazy: "!", unconscious: "?" };

export function hungerBar(hunger, max) {
  const cells = 10;
  const filled = Math.max(0, Math.min(cells, Math.round((hunger / max) * cells)));
  return `[${"█".repeat(filled)}${"░".repeat(cells - filled)}] ${hunger.toFixed(1)}`;
}

// Seats on a circle, bush gauge in the middle. `summaries` maps agent_id to the
// chronicle's AgentSummary (provider, perceived type); state is the rebuilt hour.
export function ring(state, summaries, maxHunger) {
  const n = state.agents.length;
  const seats = state.agents
    .map((seat, i) => {
      const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
      const x = 50 + 42 * Math.cos(angle);
      const y = 50 + 40 * Math.sin(angle);
      const who = summaries?.[seat.agent_id] ?? {};
      const tag = who.provider ?? "scripted";
      const mark = who.perceived_type === "Human" ? "Ⓗ" : "Ⓐ";
      const dead = seat.body_state === "dead";
      const line2 = dead
        ? `died hour ${Math.floor(seat.time_of_death ?? 0)} · ate ${seat.total_berries_consumed}`
        : `${hungerBar(seat.hunger, maxHunger)} · ate ${seat.total_berries_consumed}`;
      return `<div class="seat ${dead ? "dead" : ""}" style="left:${x}%;top:${y}%">` +
        `<div><span class="glyph">${GLYPHS[seat.body_state] ?? "?"}</span> ` +
        `<span class="bright">${esc(seat.name)}</span> ${mark} <span class="dim">${esc(tag)}</span></div>` +
        `<div>${line2}</div>` +
        `<div class="dim">${seat.body_state}${seat.body_state === "asleep" ? ` → wakes ${seat.wake_time}` : ""}</div>` +
        `</div>`;
    })
    .join("");
  const bush = state.bush;
  return `<div id="ring">${seats}<div id="bush"><pre>` +
    `  (( bush ))\n(( ${bush.current.toFixed(1)} / ${bush.max.toFixed(0)} ))\n` +
    `  +${bush.rate}/hr</pre></div></div>`;
}

export function timeline(lastHour, cursor, deathHours) {
  const cells = [];
  for (let h = 0; h <= lastHour; h++) {
    const classes = ["cell"];
    if (h === cursor) classes.push("cursor");
    if (deathHours.has(h)) classes.push("death");
    cells.push(`<span class="${classes.join(" ")}" data-hour="${h}">${deathHours.has(h) ? "†" : "·"}</span>`);
  }
  return `<div id="timeline">HR ${String(cursor).padStart(3, "0")} ${cells.join("")} ${lastHour}</div>` +
    `<div class="dim">←/→ step · Home/End jump · click a cell</div>`;
}

function toolCall(call) {
  const args = Object.entries(call.args ?? {}).map(([k, v]) => `${k}=${esc(v)}`).join(", ");
  const status = call.failed ? ` <span class="alert">FAILED</span>` : "";
  const result = call.result ? ` → ${esc(call.result)}` : "";
  return `<div class="toolcall">  did: ${esc(call.name)}(${args})${status}${result}</div>`;
}

export function turnBlock(turn) {
  const lost = turn.error && !(turn.tool_calls ?? []).length;
  const cut = turn.error && (turn.tool_calls ?? []).length;
  const badge = lost
    ? ` <span class="badge alert">TURN LOST</span>`
    : cut
      ? ` <span class="badge alert">CUT SHORT</span>`
      : "";
  const parts = [
    `<div class="turn">` +
      `<div><span class="bright">${esc(turn.agent_name)}</span> ` +
      `<span class="dim">${esc(turn.provider ?? "scripted")}${turn.model_id ? "/" + esc(turn.model_id) : ""}</span>` +
      ` · hunger ${turn.hunger.toFixed(1)} · bush ${turn.bush_berries}${badge}</div>`,
  ];
  for (const line of turn.heard ?? []) parts.push(`<div>  heard ${esc(line)}</div>`);
  for (const line of turn.misread ?? []) parts.push(`<div class="misread">  believed wrongly: ${esc(line)}</div>`);
  if (turn.reasoning) parts.push(`<div class="reasoning">${esc(turn.reasoning)}</div>`);
  for (const call of turn.tool_calls ?? []) parts.push(toolCall(call));
  if (turn.said_aloud) parts.push(`<div class="said">  summed up: ${esc(turn.said_aloud)}</div>`);
  if (turn.error) parts.push(`<div class="alert">  error: ${esc(turn.error)}</div>`);
  parts.push(`</div>`);
  return parts.join("");
}

// Who spoke to whom this hour: delivered arrows from the speak tool calls,
// crossed arrows from the chronicle's unheard list (the speaker was never told).
export function messageFlow(turns, unheard, agentCount, namesById) {
  const OFFSETS = { left: 1, left_far: 2, right: -1, right_far: -2 };
  const lines = [];
  for (const turn of turns) {
    for (const call of turn.tool_calls ?? []) {
      if (!call.name.startsWith("speak_to_") || call.failed) continue;
      const direction = call.name.slice("speak_to_".length);
      const offset = OFFSETS[direction];
      if (offset === undefined) continue;
      const target = (turn.agent_id + offset + agentCount * 2) % agentCount;
      const silent = unheard.some(
        (u) => u.speaker === turn.agent_name && u.direction === direction
      );
      const arrow = silent
        ? `<span class="unheard">${esc(turn.agent_name)} ─✕ ${esc(namesById[target] ?? "?")} (could not answer)</span>`
        : `${esc(turn.agent_name)} ─▶ ${esc(namesById[target] ?? "?")}`;
      lines.push(`${arrow}  <span class="dim">"${esc(call.args?.content ?? "")}"</span>`);
    }
  }
  return lines.length ? `<div class="flow">${lines.join("\n")}</div>` : `<div class="dim">nobody spoke</div>`;
}

export function panel(title, body) {
  return `<div class="panel"><pre class="panel-title">┌─ ${title} ─┐</pre>${body}</div>`;
}
