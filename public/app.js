// HeliosDB frontend — vanilla ES module. Fetches static JSON only.
const params = new URLSearchParams(location.search);
const HELIOS_URL = params.get("helios") || "http://127.0.0.1:8080";

const FILTERS = {
  all: null,
  planets: ["major-planet", "star"],
  moons: ["regular-moon", "irregular-moon"],
  dwarfs: ["dwarf-planet"],
  tnos: ["tno", "centaur"],
};

let INDEX = [];
let state = { q: "", cls: "all" };
let currentBody = null;

const $ = (s) => document.querySelector(s);
const grid = $("#grid"), drawer = $("#drawer"), drawerBody = $("#drawer-body");

init();

async function init() {
  const res = await fetch("data/index.json");
  INDEX = await res.json();
  renderTicker();
  bindControls();
  applyHash();
  render();
  const focus = params.get("focus");
  if (focus) openBody(focus);
}

function bindControls() {
  $("#search").addEventListener("input", (e) => { state.q = e.target.value; render(); });
  document.querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      state.cls = c.dataset.filter;
      render();
    }));
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#api-btn").addEventListener("click", () => $("#api-modal").classList.add("open"));
  $("#api-close").addEventListener("click", () => $("#api-modal").classList.remove("open"));
  $("#api-modal").addEventListener("click", (e) => {
    if (e.target.id === "api-modal") e.target.classList.remove("open");
  });
  $("#btn-json").addEventListener("click", () =>
    currentBody && navigator.clipboard.writeText(JSON.stringify(currentBody, null, 2)));
  $("#btn-url").addEventListener("click", () =>
    currentBody && navigator.clipboard.writeText(
      new URL(`data/bodies/${currentBody.id}.json`, location.href).href));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); $("#api-modal").classList.remove("open"); } });
  window.addEventListener("hashchange", applyHash);
}

function applyHash() {
  const m = location.hash.match(/^#\/bodies\/(.+)$/);
  if (m) openBody(m[1]);
}

function renderTicker() {
  const counts = {};
  for (const b of INDEX) counts[b.classification] = (counts[b.classification] || 0) + 1;
  $("#stats").innerHTML =
    `<b>${INDEX.length}</b> bodies · ` +
    Object.entries(counts).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} <b>${v}</b>`).join(" · ");
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  const classes = FILTERS[state.cls];
  return INDEX.filter((b) => {
    if (classes && !classes.includes(b.classification)) return false;
    if (!q) return true;
    const hay = [b.name, b.id, b.classification, b.parent_id || "", ...(b.aliases || [])]
      .join(" ").toLowerCase();
    return q.split(/\s+/).every((t) => hay.includes(t));
  });
}

function render() {
  const list = filtered().slice(0, 400);
  if (!list.length) { grid.innerHTML = `<div class="empty">No bodies match.</div>`; return; }
  grid.innerHTML = "";
  for (const b of list) {
    const el = document.createElement("button");
    el.className = "card";
    el.innerHTML = `<h3>${esc(b.name)}</h3>
      <div class="sub">${esc(b.id)}${b.parent_id ? " · ⟡ " + esc(b.parent_id) : ""}</div>
      <span class="badge">${esc(b.classification)}</span>`;
    el.addEventListener("click", () => openBody(b.id));
    grid.appendChild(el);
  }
}

async function openBody(id) {
  try {
    const res = await fetch(`data/bodies/${id}.json`);
    if (!res.ok) return;
    currentBody = await res.json();
    renderDrawer(currentBody);
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    if (location.hash !== `#/bodies/${id}`) history.replaceState(null, "", `#/bodies/${id}`);
  } catch { /* offline / missing file */ }
}

function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  history.replaceState(null, "", location.pathname + location.search);
}

function kvTable(obj, fmt = (v) => fmtVal(v)) {
  return "<table>" + Object.entries(obj).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td class="mono">${fmt(v)}</td></tr>`).join("") + "</table>";
}

function renderDrawer(b) {
  $("#drawer-title").textContent = b.name;
  $("#btn-helios").href = `${HELIOS_URL}/?focus=${encodeURIComponent(b.id)}`;
  const desig = (b.designations || []).map((d) =>
    `<div class="mono">${esc(d.designation)} <span style="color:var(--dim)">since ${d.since ?? "?"} · ${esc(d.kind || "")}</span></div>`).join("") || "—";
  const srcs = (b.provenance.sources || []).map((s) =>
    `<div>· ${esc(s.source_name)} <span style="color:var(--dim)">(${esc(s.retrieved_date)}): ${(s.fields_provided || []).join(", ")}</span></div>`).join("");
  const confs = (b.provenance.conflicts || []).map((c) =>
    `<div class="conflict"><b>${esc(c.field)}</b>: kept <span class="mono">${esc(String(c.chosen_value))}</span> (${esc(c.chosen_source)})<br>` +
    `<span class="rej">rejected <span class="mono">${esc(String(c.rejected_value))}</span> (${esc(c.rejected_source)})</span><br>` +
    `<span class="why">reason: ${esc(c.reason)}</span></div>`).join("") || "none — sources agree";
  drawerBody.innerHTML = `
    <h4>Identity</h4>
    <div class="mono">id: ${esc(b.id)} · ${esc(b.classification)}${b.parent_id ? " · ⟡ " + esc(b.parent_id) : ""} · ${esc(b.system || "")}</div>
    <div class="mono">aliases: ${esc((b.aliases || []).join(", ") || "—")}</div>
    <div class="mono">confidence: ${b.confidence_score}</div>
    <h4>Designations</h4>${desig}
    <h4>Physical</h4>${kvTable(b.physical || {})}
    <h4>Orbital</h4>${kvTable(b.orbital || {})}
    <h4>Discovery</h4>${kvTable(b.discovery || {})}
    <h4>Render hints</h4>${kvTable(b.render || {})}
    <h4>Sources</h4>${srcs}
    <h4>Conflicts (${(b.provenance.conflicts || []).length})</h4>${confs}`;
}

function fmtVal(v) {
  if (v && typeof v === "object") return esc(JSON.stringify(v));
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toPrecision(6).replace(/\.?0+$/, (m) => m.startsWith(".") ? "" : m);
  return esc(String(v));
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
