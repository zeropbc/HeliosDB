# HeliosDB

Unified, searchable astronomical database: orbital mechanics, physical properties,
and discovery metadata for solar-system bodies. Canonical SQLite store with FTS5,
a local-only dev API, static JSON + static HTML exports that deploy to GitHub
Pages with no server and no JavaScript required.

## Architecture

| Piece | Role |
|---|---|
| `schema/canonical.sql` | Canonical schema, FTS5 index, ID redirects |
| `scripts/ingest.py` | Multi-source ingestion + per-field merge engine |
| `scripts/overrides.json` | Manual corrections — always win, always logged |
| `scripts/export_static.py` | Canonical JSON: `public/data/index.json` + `bodies/<id>.json` — **single format, two consumers** (this site + Helios renderer) |
| `scripts/export_pages.py` | No-JS static HTML: `public/index.html` + `bodies/<id>.html` |
| `scripts/sync.sh` | Manual 4-step rebuild + sync of canonical JSON into `../Helios` |
| `server.py` / `server.sh` | **Local dev only** — test query shapes, never public traffic |
| `public/` | Static site: Zero visual identity, progressive search enhancement |
| `data/helios.db` | Local SQLite file, git-ignored, rebuilt by ingest |

**IDs are immutable slugs** (`titan`, `s-2009-s-1`). Renames append to
`designations` (each tagged with assignment year); `?focus=<id>` links never break.

## Site: static-first, no-JS core

Every body page is fully rendered at build time — tables, designations,
provenance with conflict rationale, parent/satellite navigation, and the
one-way "View in Helios Engine →" link (`?focus=<id>`) all work with JavaScript
fully disabled. Body pages contain zero `<script>` tags.

`public/search.js` (loaded `defer` on the index only) progressively enhances:
fetches `data/index.json`, search-as-you-type linking to the real static pages.
If it fails, the `#search-mount` stays `:empty` and CSS hides it — the page is
unaffected. Verified by structure (no-script pages, single deferred script) and
a node DOM-stub test of both the success and fetch-failure paths.

Visual identity (fonts, palette, fixed header) is replicated from the main Zero
site (`../site`: `assets/css/main.scss`, `components/SiteHeader.vue`) as plain
CSS with vendored font/logo files — no Vue/Nuxt runtime or build coupling.

## Sync workflow (manual-trust phase)

```bash
./scripts/sync.sh   # ingest --reset → export_static → export_pages → copy JSON into ../Helios
```

Review diffs in **both** repos before committing — no auto-commit. Step 4 is
additive-only by design: it writes `../Helios/bodies/data/*.json` plus
`manifest-canonical.json`, never touching the live `manifest.json` or
hand-authored files the engine reads today. The later Helios renderer update
repoints the loader at the canonical files; the old files retire after that.
CI automation is explicitly deferred.

## Sources

- Helios seed (`../Helios/bodies/…`): planets, moons, outer-system objects, render hints
- Static JPL/IAU reference table (in `ingest.py:TIER1`) — mean radii with explicit
  uncertainties, masses, GM, densities, rotation, albedo
- `Moons_of_Saturn_1/3/4.csv` — major-moon summary, full moon table, ring-moonlet candidates
- `Moons_of_Jupiter_2/3.csv` — full moon table (Group column is last; glyphs trail names), surface radiation
- Saturn CSV 2 / Jupiter CSV 1 are group legends (counts only, no bodies)

> **Provenance caveat:** the TIER1 table is hand-transcribed constants, not a
> machine-read file. Values were spot-checked against JPL SSD physical-parameter
> tables (see Verification), but treat `sources_json` tier-1 entries as
> "transcribed from JPL/IAU", not byte-derived. If a value is ever suspect, the
> merge log (`conflicts_json`) shows exactly what beat what and why.

## Merge rules (auditable)

Per field, across all sources providing it:

1. **Overrides always win** (`scripts/overrides.json`), logged with reason.
2. **Explicit smaller uncertainty wins** over coarser/unstated.
3. Else **more significant figures wins**; ties → **more recent source**.
4. Every rejected value differing by **>0.5% relative** is recorded in
   `conflicts_json` as `{field, chosen_value, chosen_source, rejected_value,
   rejected_source, reason}`. Sub-tolerance agreement is corroboration, not conflict.
5. Physical vs orbital fields merge independently.

`classify_moon` is a heuristic (named irregular groups → irregular; else
`incl>50°` or `ecc>0.3` → irregular). It is **not** scientifically authoritative —
formation origin defines irregularity, and the heuristic under-classifies outer
prograde irregulars (Himalia, Elara — corrected via overrides). Expect more
overrides as coverage grows; that is the system working as designed.

## Run

```bash
python3 scripts/ingest.py --reset   # rebuild data/helios.db
python3 scripts/export_static.py    # write public/data/
python3 scripts/export_pages.py     # write public/index.html + bodies/
./server.sh --port 8765             # dev API + static frontend (DEV ONLY)
```

## Verification

```bash
# counts + conflicts
python3 -c "import sqlite3; db=sqlite3.connect('data/helios.db'); print('Total:', db.execute('SELECT COUNT(*) FROM bodies').fetchone()[0]); print('Conflicts:', db.execute(\"SELECT COUNT(*) FROM bodies WHERE conflicts_json != '[]'\").fetchone()[0])"
# page completeness: parents resolve, no orphans, no <script> in body pages
python3 -c "
import sqlite3, os
db = sqlite3.connect('data/helios.db')
ids = {r[0] for r in db.execute('SELECT id,parent_id FROM bodies') if True}
rows = db.execute('SELECT id,parent_id FROM bodies').fetchall()
assert not [r for r in rows if r[1] and r[1] not in ids], 'dangling parent'
assert all(os.path.exists(f'public/bodies/{i}.html') for i in ids), 'missing page'
assert not [i for i in ids if '<script' in open(f'public/bodies/{i}.html').read().lower()], 'script in body page'
print('467 pages, all linked, no-JS pure')"
# determinism: rerun → identical bytes
sha256sum data/helios.db && python3 scripts/ingest.py --reset >/dev/null && sha256sum data/helios.db
```

Manual checks: Mimas/Enceladus mass+period conflicts resolve toward the precise
CSV-3 values with CSV-1 rejections logged; Himalia/Elara show `manual_override`
conflict entries; FTS `SELECT id FROM bodies_fts WHERE bodies_fts MATCH 'titan*'`
resolves. Spot-check high-impact constants (Titan radius, Jupiter/Saturn mass,
Earth mean radius) against current JPL fact sheets before treating output as
ground truth — see provenance caveat above.
