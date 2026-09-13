#!/usr/bin/env python3
"""HeliosDB static page export — generates no-JS HTML from data/helios.db.

  public/index.html          — classification + alphabetical index (static)
  public/bodies/<id>.html    — one page per body, all data baked in

No client-side rendering is required to see any content. search.js (loaded
with defer on index.html only) progressively enhances with search-as-you-type.
Body pages contain zero <script> tags.
"""

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "helios.db"
PUBLIC_DIR = ROOT
BODIES_DIR = PUBLIC_DIR / "bodies"

CSS_VERSION = "6"  # bump when styles.css changes (cache-bust)

CLASS_ORDER = ["star", "major-planet", "dwarf-planet", "regular-moon",
               "irregular-moon", "centaur", "tno", "asteroid", "comet", "exoplanet"]
CLASS_TITLES = {"star": "Stars", "major-planet": "Major Planets",
                "dwarf-planet": "Dwarf Planets", "regular-moon": "Regular Moons",
                "irregular-moon": "Irregular Moons", "centaur": "Centaurs",
                "tno": "Trans-Neptunian Objects", "asteroid": "Asteroids",
                "comet": "Comets", "exoplanet": "Exoplanets"}

# column -> (label, unit)
PHYSICAL_LABELS = [
    ("radius_km", "Mean radius", "km"),
    ("radius_uncertainty_km", "Radius uncertainty", "± km"),
    ("equatorial_radius_km", "Equatorial radius", "km"),
    ("polar_radius_km", "Polar radius", "km"),
    ("dimensions_json", "Triaxial dimensions", "km"),
    ("mass_kg", "Mass", "kg"),
    ("gm_km3_s2", "GM", "km³/s²"),
    ("density_g_cm3", "Bulk density", "g/cm³"),
    ("surface_gravity_m_s2", "Surface gravity", "m/s²"),
    ("escape_velocity_km_s", "Escape velocity", "km/s"),
    ("rotation_period_h", "Rotation period", "h"),
    ("axial_tilt_deg", "Axial tilt", "°"),
    ("geometric_albedo", "Geometric albedo", None),
    ("bond_albedo", "Bond albedo", None),
    ("spectral_type", "Spectral type", None),
    ("absolute_magnitude_h", "Absolute magnitude (H)", None),
    ("apparent_magnitude_v", "Apparent magnitude (V)", None),
    ("mean_temperature_k", "Mean temperature", "K"),
    ("atmosphere_summary", "Atmosphere", None),
    ("surface_radiation_rem_day", "Surface radiation", "rem/day"),
]
ORBITAL_LABELS = [
    ("semi_major_axis_au", "Semi-major axis", "AU"),
    ("semi_major_axis_km", "Semi-major axis", "km"),
    ("periapsis_au", "Periapsis", "AU"),
    ("apoapsis_au", "Apoapsis", "AU"),
    ("eccentricity", "Eccentricity", None),
    ("inclination_deg", "Inclination", "°"),
    ("longitude_ascending_node_deg", "Longitude of ascending node", "°"),
    ("argument_periapsis_deg", "Argument of periapsis", "°"),
    ("mean_anomaly_deg", "Mean anomaly", "°"),
    ("mean_longitude_deg", "Mean longitude", "°"),
    ("orbital_period_days", "Orbital period", "days"),
    ("orbital_period_years", "Orbital period", "years"),
    ("orbital_velocity_km_s", "Orbital velocity", "km/s"),
    ("epoch_jd", "Epoch", "JD"),
]
DISCOVERY_LABELS = [
    ("discovery_year", "Discovery year", None),
    ("announcement_year", "Announcement year", None),
    ("discoverer", "Discoverer", None),
    ("discovery_site", "Discovery site", None),
    ("naming_origin", "Naming origin", None),
]

FIELD_LABELS = {c: l for c, l, _ in PHYSICAL_LABELS + ORBITAL_LABELS + DISCOVERY_LABELS}
FIELD_LABELS["longitude_periapsis_deg"] = "Longitude of periapsis"  # JPL ϖ; distinct from argument (ω)


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def fmt(v):
    if isinstance(v, float):
        if v != v:
            return "—"
        return f"{v:.6g}"
    return esc(v)


def fmt_json_cell(raw):
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return esc(raw)
    if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
        return " × ".join(fmt(x) for x in v)
    if isinstance(v, dict) and "rings" in v:
        return ", ".join(
            f"{esc(r.get('name', '?'))} {fmt(r.get('inner_km'))}–{fmt(r.get('outer_km'))} km"
            for r in v["rings"])
    return esc(json.dumps(v, sort_keys=True))


def md_table(rows):
    if not rows:
        return "—"
    lines = [
        "| Field | Value | Unit |",
        "| --- | ---: | --- |",
    ]
    for k, v, u in rows:
        lines.append(f"| {esc(k)} | {v} | {esc(u) if u else ''} |")
    return "\n".join(lines)


def table(rows):
    if not rows:
        return "<p class=\"dim\">—</p>"
    return markdown.markdown(md_table(rows), extensions=["tables"])


def header(nav_extra=""):
    return f"""<header class="site-header">
  <div class="header-row">
    <a href="../index.html" class="brand" aria-label="HeliosDB home">
      <img src="../favicon.svg" alt="" class="brand-mark" width="24" height="24">
      <span class="brand-word">HeliosDB</span>
    </a>
    <nav class="nav" aria-label="Main Navigation">
      <a href="../index.html">Index</a>
      <a href="https://zeropbc.github.io/Helios/">Helios Engine</a>
      <a href="https://github.com/zeropbc/HeliosDB">GitHub</a>
    </nav>
    <a href="https://zeropbc.github.io/" class="zero-link" aria-label="Zero Labs">
      <img src="../assets/Logo Dark BG-less.svg" alt="" class="brand-logo brand-logo--dark" width="24" height="27">
      <img src="../assets/Logo Light BG-less.svg" alt="" class="brand-logo brand-logo--light" width="24" height="27">
    </a>
  </div>
</header>{nav_extra}"""


def body_page(d, children, by_id, helios_url):
    bid = d["id"]
    phys = [(l, fmt_json_cell(d[c]) if c.endswith("_json") else fmt(d[c]), u)
            for c, l, u in PHYSICAL_LABELS if d.get(c) is not None]
    orb = [(l, fmt(d[c]), u) for c, l, u in ORBITAL_LABELS if d.get(c) is not None]
    disc = [(l, fmt(d[c]), None) for c, l, _ in DISCOVERY_LABELS if d.get(c) is not None]
    desigs = json.loads(d["designations_json"] or "[]")
    aliases = json.loads(d["aliases_json"] or "[]")
    sources = json.loads(d["sources_json"] or "[]")
    conflicts = json.loads(d["conflicts_json"] or "[]")
    rings = json.loads(d["rings_json"] or "{}")
    rates = json.loads(d["rates_json"] or "{}")

    parent_link = (f'<a href="{by_id[d["parent_id"]]["id"]}.html">{esc(by_id[d["parent_id"]]["name"])}</a>'
                   if d.get("parent_id") and d["parent_id"] in by_id else "—")
    sats = "".join(
        f'<li><a href="{esc(c["id"])}.html">{esc(c["name"])}</a> '
        f'<span class="dim">{esc(c["classification"])}</span></li>'
        for c in children)
    desig_rows = "".join(
        f"<tr><td>{esc(g.get('designation', ''))}</td>"
        f"<td>{esc(g.get('since') or '?')}</td>"
        f"<td class=\"dim\">{esc(g.get('kind') or '')}</td></tr>" for g in desigs)
    conf_rows = "".join(
        f"<div class=\"conflict\"><b title=\"{esc(c['field'])}\">{esc(FIELD_LABELS.get(c['field'], c['field']))}</b>: kept "
        f"<span class=\"num\">{esc(c['chosen_value'])}</span> ({esc(c['chosen_source'])})<br>"
        f"<span class=\"rej\">rejected <span class=\"num\">{esc(c['rejected_value'])}</span> "
        f"({esc(c['rejected_source'])})</span><br>"
        f"<span class=\"why\">reason: {esc(c['reason'])}</span></div>" for c in conflicts)
    src_rows = "".join(
        f"<div>· {esc(s['source_name'])} <span class=\"dim\">({esc(s['retrieved_date'])}): "
        f"{esc(', '.join(FIELD_LABELS.get(f, f) for f in s.get('fields_provided', [])))}</span></div>" for s in sources)
    rates_rows = [(FIELD_LABELS.get(k, k), fmt(v), "per century")
                  for k, v in sorted(rates.items())]
    render_rows = []
    if d.get("render_color_hex"):
        render_rows.append(("Color hex", esc(d["render_color_hex"]), None))
    if d.get("render_radius") is not None:
        render_rows.append(("Render radius", fmt(d["render_radius"]), None))
    if rings.get("rings"):
        render_rows.append(("Rings", fmt_json_cell(d["rings_json"]), None))
    record_rows = [("Created (snapshot)", esc(d["created_at"]), None),
                   ("Updated (snapshot)", esc(d["updated_at"]), None)]
    if d.get("superseded_by") and d["superseded_by"] in by_id:
        sb = by_id[d["superseded_by"]]
        record_rows.append(("Superseded by",
                            f'<a href="{esc(sb["id"])}.html">{esc(sb["name"])}</a>', None))
    color = d.get("render_color_hex")
    swatch = (f'<span class="swatch" style="background:{esc(color)}"></span>' if color else "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(d["name"])}</title>
<link rel="stylesheet" href="../styles.css?v={CSS_VERSION}">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
</head>
<body>
{header()}
<main class="wrap">
  <p class="crumb"><a href="../index.html">Index</a> / {esc(d["classification"])} /</p>
  <h1>{swatch}{esc(d["name"])}</h1>
  <p class="dim"><span class="badge">{esc(d["classification"])}</span> <span class="mono">id: {esc(bid)}</span>
  {(" · aliases: " + esc(", ".join(aliases))) if aliases else ""} · confidence {esc(d["confidence_score"])}</p>
  <p><a class="btn" href="{esc(helios_url)}/?focus={esc(bid)}">View in Helios Engine →</a></p>

  <h2>Designations</h2>
  {("<table><thead><tr><th>Designation</th><th>Since</th><th>Kind</th></tr></thead><tbody>" + desig_rows + "</tbody></table>") if desig_rows else "<p class=\"dim\">—</p>"}

  <h2>Physical</h2>
  {table(phys)}

  <h2>Orbital</h2>
  {table(orb)}

  <h2>Secular rates</h2>
  {table(rates_rows)}

  <h2>Discovery</h2>
  {table(disc)}

  <h2>Render hints</h2>
  {table(render_rows)}

  <h2>System</h2>
  <p>Orbits: {parent_link}</p>
  {("<h3>Satellites</h3><ul class=\"satlist\">" + sats + "</ul>") if sats else ""}

  <h2>Provenance</h2>
  <h3>Sources</h3>
  {src_rows or "<p class=\"dim\">—</p>"}
  <h3>Conflicts ({len(conflicts)})</h3>
  {conf_rows or "<p class=\"dim\">none — sources agree</p>"}

  <h2>Record</h2>
  {table(record_rows)}
</main>
</body>
</html>
"""


def index_page(groups, alpha, total, helios_url):
    sections = ""
    for cls in CLASS_ORDER:
        items = groups.get(cls, [])
        if not items:
            continue
        links = "".join(
            f"<li><a href=\"bodies/{esc(b['id'])}.html\">{esc(b['name'])}</a>"
            + (f" <span class=\"dim\">⟡ {esc(b['parent_name'])}</span>" if b.get("parent_name") else "")
            + "</li>" for b in items)
        sections += f"<section><h2>{esc(CLASS_TITLES.get(cls, cls))} ({len(items)})</h2><ul class=\"idx\">{links}</ul></section>"
    az = ""
    for letter in sorted(alpha):
        links = "".join(
            f"<li><a href=\"bodies/{esc(b['id'])}.html\">{esc(b['name'])}</a></li>"
            for b in alpha[letter])
        az += f"<section><h3>{esc(letter)}</h3><ul class=\"idx\">{links}</ul></section>"
    stats = " · ".join(
        f"{esc(CLASS_TITLES.get(c, c))} <b>{len(groups.get(c, []))}</b>"
        for c in CLASS_ORDER if groups.get(c))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HeliosDB</title>
<link rel="stylesheet" href="styles.css?v={CSS_VERSION}">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<script defer src="search.js"></script>
</head>
<body>
<header class="site-header">
  <div class="header-row">
    <a href="index.html" class="brand" aria-label="HeliosDB home">
      <img src="favicon.svg" alt="" class="brand-mark" width="24" height="24">
      <span class="brand-word">HeliosDB</span>
    </a>
    <nav class="nav" aria-label="Main Navigation">
      <a href="index.html">Index</a>
      <a href="https://zeropbc.github.io/Helios/">Helios Engine</a>
      <a href="https://github.com/zeropbc/HeliosDB">GitHub</a>
    </nav>
    <a href="https://zeropbc.github.io/" class="zero-link" aria-label="Zero Labs">
      <img src="assets/Logo Dark BG-less.svg" alt="" class="brand-logo brand-logo--dark" width="24" height="27">
      <img src="assets/Logo Light BG-less.svg" alt="" class="brand-logo brand-logo--light" width="24" height="27">
    </a>
  </div>
</header>
<main class="wrap">
  <h1>HeliosDB</h1>
  <p class="dim">Canonical astronomical database · <b>{total}</b> bodies</p>
  <div id="search-mount"></div>
  <p class="ticker">{stats}</p>
  {sections}
  <h2 class="az-head">Alphabetical index</h2>
  {az}
  <h2>Data access</h2>
  <p>No live API in production — consume the static JSON directly:</p>
  <pre><code>GET data/index.json            # [{{id, name, aliases, classification, parent_id}}]
GET data/bodies/&lt;id&gt;.json     # full canonical record</code></pre>
  <p>Local dev mirror (<code>./server.sh</code>, dev only): <code>/api/v1/bodies?q=…</code>,
  <code>/api/v1/bodies/&lt;id&gt;</code>, <code>/api/v1/systems/&lt;parent_id&gt;</code>,
  <code>/api/v1/export/helios</code>, <code>/api/v1/stats</code>.</p>
</main>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Generate static HTML pages from helios.db")
    ap.add_argument("--helios-url", default="https://zeropbc.github.io/Helios",
                    help="Base URL for 'View in Helios Engine' links")
    args = ap.parse_args()
    if not DB_PATH.exists():
        sys.exit(f"error: {DB_PATH} missing — run scripts/ingest.py first")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM bodies ORDER BY name")]
    db.close()
    by_id = {r["id"]: r for r in rows}
    children = {}
    for r in rows:
        if r.get("parent_id"):
            children.setdefault(r["parent_id"], []).append(r)
    for kids in children.values():
        kids.sort(key=lambda r: (r.get("semi_major_axis_km") or 0))

    BODIES_DIR.mkdir(parents=True, exist_ok=True)
    written = set()
    for r in rows:
        written.add(r["id"])
        (BODIES_DIR / f"{r['id']}.html").write_text(
            body_page(r, children.get(r["id"], []), by_id, args.helios_url.rstrip("/")))
    groups, alpha = {}, {}
    for r in rows:
        groups.setdefault(r["classification"], []).append({
            "id": r["id"], "name": r["name"],
            "parent_name": (by_id[r["parent_id"]]["name"] if r.get("parent_id") in by_id else "")})
        alpha.setdefault((r["name"][:1] or "#").upper(), []).append(
            {"id": r["id"], "name": r["name"]})
    (PUBLIC_DIR / "index.html").write_text(
        index_page(groups, alpha, len(rows), args.helios_url.rstrip("/")))
    stale = [p for p in BODIES_DIR.glob("*.html") if p.stem not in written]
    for p in stale:
        p.unlink()
    print(f"Generated {len(rows)} body pages + index → {PUBLIC_DIR}"
          + (f" (removed {len(stale)} stale)" if stale else ""))


if __name__ == "__main__":
    main()
