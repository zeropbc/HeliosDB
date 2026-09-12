#!/usr/bin/env python3
"""HeliosDB ingestion pipeline — normalizes multi-source astronomical records
into the canonical schema (schema/canonical.sql).

Sources (in read order):
  1. Helios seed data  (bodies/manifest.json, moons.json, outer-system.json)
  2. JPL / IAU reference table (static, tier 1)
  3. Saturn CSV 1 — major-moon summary (coarse values)
  4. Saturn CSV 3 — full Saturn-moon table (precise values)
  5. Saturn CSV 4 — ring-moonlet candidates
  6. Jupiter CSV 2 — full Jupiter-moon table (precise values)
  7. Jupiter CSV 3 — surface radiation (rem/day)
  8. scripts/overrides.json — manual corrections, always win

(Saturn CSV 2 and Jupiter CSV 1 are group legends — counts only, no bodies.)

Merge rule (per plan): precision wins (explicit smaller uncertainty, else more
significant figures); ties broken by recency. Every materially-different
rejected value is recorded in conflicts_json. Reruns are byte-identical.
"""

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
HELIOS = ROOT.parent / "Helios"
DB_PATH = ROOT / "data" / "helios.db"
SCHEMA_PATH = ROOT / "schema" / "canonical.sql"
OVERRIDES_PATH = Path(__file__).parent / "overrides.json"

AU_KM = 149_597_870.7
SNAPSHOT_TS = "2026-09-12T00:00:00Z"   # fixed → reruns are byte-identical
REL_TOL = 0.005                        # >0.5% relative difference = real conflict
J2000 = 2451545.0

# ----------------------------------------------------------------------------
# static reference data (JPL / IAU, tier 1)
# Transcribed constants — verified 2026-09-12 against JPL SSD phys_par
# (satellites) and phys_par.html + astro_par.html (planets). Two real
# transcription errors were caught and fixed here: Phobos radius 11.27→11.08,
# Ganymede radius 2634.1→2631.2, Saturn rotation digit-swap 10.5561→10.6562.
# Charon density intentionally NOT taken from the JPL scrape (suspect 1.853
# triple, fails GM/radius consistency) — kept New-Horizons 1.702.
# radius_uncertainty_km present → mean-radius values win over coarser seed data
# ----------------------------------------------------------------------------
TIER1 = {
    "sun":     dict(radius_km=695700, equatorial_radius_km=695700, mass_kg=1.989e30,
                    gm_km3_s2=132712440018, density_g_cm3=1.408, rotation_period_h=609.12,
                    mean_temperature_k=5772, spectral_type="G2V"),
    "mercury": dict(radius_km=2439.7, radius_uncertainty_km=1.0, mass_kg=3.301e23,
                    gm_km3_s2=22031.869, density_g_cm3=5.427, rotation_period_h=1407.6,
                    mean_temperature_k=440, axial_tilt_deg=0.034, geometric_albedo=0.142),
    "venus":   dict(radius_km=6051.8, radius_uncertainty_km=1.0, mass_kg=4.867e24,
                    gm_km3_s2=324858.592, density_g_cm3=5.243, rotation_period_h=-5832.5,
                    mean_temperature_k=737, axial_tilt_deg=177.36, geometric_albedo=0.689),
    "earth":   dict(radius_km=6371.0, radius_uncertainty_km=0.1, equatorial_radius_km=6378.1,
                    polar_radius_km=6356.8, mass_kg=5.972e24, gm_km3_s2=398600.4355,
                    density_g_cm3=5.514, rotation_period_h=23.9345, axial_tilt_deg=23.44,
                    geometric_albedo=0.434, bond_albedo=0.306, mean_temperature_k=288),
    "mars":    dict(radius_km=3389.5, radius_uncertainty_km=0.2, mass_kg=6.417e23,
                    gm_km3_s2=42828.376, density_g_cm3=3.933, rotation_period_h=24.6229,
                    axial_tilt_deg=25.19, mean_temperature_k=210, geometric_albedo=0.170),
    "jupiter": dict(radius_km=69911, radius_uncertainty_km=6.0, equatorial_radius_km=71492,
                    polar_radius_km=66854, mass_kg=1.898e27, gm_km3_s2=126686534,
                    density_g_cm3=1.326, rotation_period_h=9.9250, axial_tilt_deg=3.13,
                    geometric_albedo=0.52, mean_temperature_k=165),
    "saturn":  dict(radius_km=58232, radius_uncertainty_km=6.0, equatorial_radius_km=60268,
                    polar_radius_km=54364, mass_kg=5.683e26, gm_km3_s2=37931206,
                    density_g_cm3=0.687, rotation_period_h=10.6562, axial_tilt_deg=26.73,
                    geometric_albedo=0.47, mean_temperature_k=134),
    "uranus":  dict(radius_km=25362, radius_uncertainty_km=7.0, equatorial_radius_km=25559,
                    polar_radius_km=24973, mass_kg=8.681e25, gm_km3_s2=5793966,
                    density_g_cm3=1.271, rotation_period_h=-17.24, axial_tilt_deg=97.77,
                    geometric_albedo=0.488, mean_temperature_k=76),
    "neptune": dict(radius_km=24622, radius_uncertainty_km=19.0, equatorial_radius_km=24764,
                    polar_radius_km=24341, mass_kg=1.024e26, gm_km3_s2=6836529,
                    density_g_cm3=1.638, rotation_period_h=16.11, axial_tilt_deg=28.32,
                    geometric_albedo=0.442, mean_temperature_k=72),
    "moon":    dict(radius_km=1737.4, radius_uncertainty_km=0.1, mass_kg=7.342e22,
                    gm_km3_s2=4902.8001, density_g_cm3=3.344, rotation_period_h=655.728),
    "titan":      dict(radius_km=2574.76, radius_uncertainty_km=0.02, mass_kg=1.3452e23,
                       density_g_cm3=1.882, rotation_period_h=382.69,
                       discovery_year=1655, discoverer="Christiaan Huygens"),
    "enceladus":  dict(radius_km=252.1, radius_uncertainty_km=0.2, mass_kg=1.0803e20,
                       density_g_cm3=1.6097),
    "mimas":      dict(radius_km=198.2, radius_uncertainty_km=0.4, mass_kg=3.75e19,
                       density_g_cm3=1.1501),
    "tethys":     dict(radius_km=531.1, radius_uncertainty_km=0.6, mass_kg=6.17e20,
                       density_g_cm3=0.984),
    "dione":      dict(radius_km=561.4, radius_uncertainty_km=0.4, mass_kg=1.0955e21,
                       density_g_cm3=1.4781),
    "rhea":       dict(radius_km=763.5, radius_uncertainty_km=0.5, mass_kg=2.31e21,
                       density_g_cm3=1.2372),
    "iapetus":    dict(radius_km=734.3, radius_uncertainty_km=2.8, mass_kg=1.81e21,
                       density_g_cm3=1.088),
    "phoebe":     dict(radius_km=106.5, radius_uncertainty_km=0.7, mass_kg=8.3123e18,
                       density_g_cm3=1.6428, discovery_year=1898,
                       discoverer="William Henry Pickering"),
    "io":         dict(radius_km=1821.49, radius_uncertainty_km=0.5, mass_kg=8.932e22,
                       density_g_cm3=3.528),
    "europa":     dict(radius_km=1560.8, radius_uncertainty_km=0.3, mass_kg=4.800e22,
                       density_g_cm3=3.013),
    "ganymede":   dict(radius_km=2631.2, radius_uncertainty_km=1.7, mass_kg=1.4815e23,
                       density_g_cm3=1.9416),
    "callisto":   dict(radius_km=2410.3, radius_uncertainty_km=1.5, mass_kg=1.0757e23,
                       density_g_cm3=1.834),
    "triton":     dict(radius_km=1352.6, radius_uncertainty_km=2.4, mass_kg=2.139e22,
                       density_g_cm3=2.0649),
    "pluto":      dict(radius_km=1188.3, radius_uncertainty_km=0.8, mass_kg=1.303e22,
                       density_g_cm3=1.854),
    "miranda":    dict(radius_km=235.8, radius_uncertainty_km=0.7),
    "ariel":      dict(radius_km=578.9, radius_uncertainty_km=0.6),
    "umbriel":    dict(radius_km=584.7, radius_uncertainty_km=2.8),
    "titania":    dict(radius_km=788.9, radius_uncertainty_km=1.8),
    "oberon":     dict(radius_km=761.4, radius_uncertainty_km=2.6),
    "charon":     dict(radius_km=606.0, radius_uncertainty_km=0.5, mass_kg=1.586e21,
                       density_g_cm3=1.702),
    "janus":      dict(radius_km=89.2, radius_uncertainty_km=0.8),
    "epimetheus": dict(radius_km=58.2, radius_uncertainty_km=1.2),
    "atlas":      dict(radius_km=15.1, radius_uncertainty_km=0.8),
    "prometheus": dict(radius_km=43.1, radius_uncertainty_km=1.2),
    "pandora":    dict(radius_km=40.6, radius_uncertainty_km=1.5),
    "pan":        dict(radius_km=14.0, radius_uncertainty_km=1.2),
    "daphnis":    dict(radius_km=4.9, radius_uncertainty_km=1.0),
    "phobos":     dict(radius_km=11.08, radius_uncertainty_km=0.04, mass_kg=1.0618e16,
                       density_g_cm3=1.872),
    "deimos":     dict(radius_km=6.2, radius_uncertainty_km=0.24, mass_kg=1.4413e15,
                       density_g_cm3=1.471),
}

ALIASES = {"sun": ["Sol"], "moon": ["Luna"], "earth": ["Terra"]}

CURATED_DESIGNATIONS = {
    "pluto": [{"designation": "134340 Pluto", "since": 2006, "kind": "iau-number"}],
    "titan": [{"designation": "Saturn VI", "since": 1848, "kind": "roman-numeral"}],
}

SATURN_RINGS = {"rings": [
    {"name": "D", "inner_km": 66900, "outer_km": 74510},
    {"name": "C", "inner_km": 74658, "outer_km": 92000},
    {"name": "B", "inner_km": 92000, "outer_km": 117580},
    {"name": "A", "inner_km": 122170, "outer_km": 136775},
    {"name": "F", "inner_km": 140180, "outer_km": 140180},
    {"name": "G", "inner_km": 165800, "outer_km": 173800},
    {"name": "E", "inner_km": 180000, "outer_km": 480000},
]}

SOURCES = {
    "helios-seed":      {"source_name": "Helios seed data", "source_url": "https://github.com/zeropbc/Helios",
                         "retrieved_date": "2026-09-01"},
    "static-jpl-iau":   {"source_name": "NASA JPL Solar System Exploration / IAU", "source_url": "https://solarsystem.nasa.gov",
                         "retrieved_date": "2025-01-15"},
    "saturn-csv1":      {"source_name": "Saturn major moons summary (JPL/Cassini via Helios db)",
                         "source_url": "https://ssd.jpl.nasa.gov/sats/elem/", "retrieved_date": "2026-03-01"},
    "saturn-csv3":      {"source_name": "Saturn moons table (JPL/SSD via Helios db)",
                         "source_url": "https://ssd.jpl.nasa.gov/sats/elem/", "retrieved_date": "2026-03-01"},
    "saturn-csv4":      {"source_name": "Saturn ring-moonlet candidates (NASA via Helios db)",
                         "source_url": "https://ssd.jpl.nasa.gov/sats/elem/", "retrieved_date": "2026-03-01"},
    "jupiter-csv2":     {"source_name": "Jupiter moons table (JPL/SSD via Helios db)",
                         "source_url": "https://ssd.jpl.nasa.gov/sats/elem/", "retrieved_date": "2026-03-01"},
    "jupiter-csv3":     {"source_name": "Jupiter moon surface radiation (NASA Galileo via Helios db)",
                         "source_url": "https://solarsystem.nasa.gov", "retrieved_date": "2026-03-01"},
    "render-seed":      {"source_name": "Helios render hints (curated)", "source_url": "https://github.com/zeropbc/Helios",
                         "retrieved_date": "2026-09-01"},
}
# final deterministic tiebreak order (lower wins)
SOURCE_ORDER = ["static-jpl-iau", "saturn-csv3", "jupiter-csv2", "saturn-csv1",
                "saturn-csv4", "jupiter-csv3", "helios-seed", "render-seed",
                "manual-override"]

SYSTEM_MAP = {"sun": "Solar System", "earth": "Earth-Moon System", "mars": "Martian System",
              "jupiter": "Jovian System", "saturn": "Saturnian System",
              "uranus": "Uranian System", "neptune": "Neptunian System",
              "pluto": "Plutonian System"}
MAJOR = {"mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"}
DWARFS = {"pluto", "eris", "haumea", "makemake", "gonggong", "quaoar", "orcus",
          "sedna", "salacia", "varda", "ixion", "varuna"}
CENTAURS = {"chiron", "chariklo", "pholus", "hidalgo"}
OUTER_CLASS = {"dwarf-planet": "dwarf-planet", "dwarf-planet-candidate": "dwarf-planet",
               "centaur": "centaur", "detached-object": "tno", "tno": "tno"}
IRREGULAR_GROUPS = ("norse", "inuit", "gallic", "himalia", "carpo", "ananke",
                    "carme", "pasiphae", "themisto", "valetudo")
GLYPHS = "♠♦♣‡†§±♥"

# ----------------------------------------------------------------------------
# parsing helpers
# ----------------------------------------------------------------------------
def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def num(s):
    """First plain float in a string (handles commas, ≈, ±, unicode minus, units)."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").replace("−", "-").replace("–", "-")
    m = re.search(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s)
    return float(m.group()) if m else None


def num_sci(s):
    """Parse flattened scientific notation like '1.35×1023' (=1.35e23)."""
    if s is None:
        return None
    m = re.search(r"([\d.]+)\s*×\s*1?0?(\d+)", str(s))
    if m:
        return float(m.group(1)) * (10 ** int(m.group(2)))
    return num(s)


def count_sigfigs(raw) -> int:
    """Significant figures of the first numeric token in a raw string."""
    if raw is None:
        return 0
    approx = "≈" in str(raw) or "~" in str(raw)
    m = re.search(r"\d[\d.,]*", str(raw))
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group()).lstrip("0")
    sf = max(len(digits), 1)
    return max(sf - (1 if approx else 0), 1)


def color_hex(c):
    return f"#{int(c):06x}" if c is not None else None


def classify_moon(inc, ecc, group=""):
    g = (group or "").lower()
    if any(k in g for k in IRREGULAR_GROUPS):
        return "irregular-moon"
    inc = inc or 0.0
    ecc = ecc or 0.0
    return "irregular-moon" if (inc > 50 or ecc > 0.3) else "regular-moon"


def parse_diameter_cell(raw: str):
    """'28.2 (35 × 28 × 21)' → (mean_diameter, [a,b,c] or [], radius_uncertainty)."""
    if not raw or raw.strip() in ("—", "-", "?", ""):
        return None, [], None
    tri = re.findall(r"(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)\s*[×x]\s*(\d+(?:\.\d+)?)", raw)
    first = num(str(raw).split("\n")[0])
    if tri:
        a, b, c = (float(tri[0][0]), float(tri[0][1]), float(tri[0][2]))
        r = [(a / 2), (b / 2), (c / 2)]
        geo = (r[0] * r[1] * r[2]) ** (1 / 3)
        unc = (max(r) - min(r)) / 2
        return geo * 2, [a, b, c], unc
    if first:
        return first, [], None
    return None, [], None


def clean_name(raw: str) -> str:
    s = (raw or "").replace("­", "").strip()  # strip soft-hyphen wrap artifacts
    s = re.sub(rf"^[{GLYPHS}\s—–-]+", "", s)
    s = re.sub(rf"[{GLYPHS}\s]+$", "", s)
    return s.strip()


# ----------------------------------------------------------------------------
# candidate model + merge engine
# ----------------------------------------------------------------------------
class Body:
    def __init__(self, bid, name):
        self.id = bid
        self.name = name
        self.cands = {}          # field -> list of candidate dicts
        self.meta = {}           # dimensions, rings, spectral_type, override conflicts
        self.designations = []   # [{designation, since, kind}]
        self.aliases = []
        self.render = {}
        self.rates = {}
        self.classification = None
        self.parent_id = None
        self.system = None

    def add(self, field, value, source, raw=None, uncertainty=None):
        if value is None:
            return
        if isinstance(value, float) and (value != value):  # NaN guard
            return
        self.cands.setdefault(field, []).append({
            "value": value, "source": source,
            "retrieved": SOURCES[source]["retrieved_date"],
            "uncertainty": uncertainty,
            "sigfigs": count_sigfigs(raw if raw is not None else value),
        })


def pick_winner(pool):
    if len(pool) == 1:
        return pool[0]
    dated = sorted(pool, key=lambda c: c["retrieved"], reverse=True)
    tied = [c for c in dated if c["retrieved"] == dated[0]["retrieved"]]
    if len(tied) == 1:
        return tied[0]
    tied.sort(key=lambda c: SOURCE_ORDER.index(c["source"]))
    return tied[0]


def merge_field(field, cands):
    """Returns (winner_value, conflicts). Plan rule: uncertainty → sigfigs → recency."""
    if len(cands) == 1:
        return cands[0]["value"], []
    with_unc = [c for c in cands if c["uncertainty"] is not None]
    if with_unc:
        best_unc = min(c["uncertainty"] for c in with_unc)
        pool = [c for c in with_unc if c["uncertainty"] == best_unc]
        reason = "smaller_uncertainty"
    else:
        best_sf = max(c["sigfigs"] for c in cands)
        pool = [c for c in cands if c["sigfigs"] == best_sf]
        reason = "higher_precision"
    winner = pick_winner(pool)
    conflicts = []
    for c in cands:
        if c is winner:
            continue
        if materially_differs(winner["value"], c["value"]):
            conflicts.append({
                "field": field,
                "chosen_value": winner["value"], "chosen_source": src_name(winner["source"]),
                "rejected_value": c["value"], "rejected_source": src_name(c["source"]),
                "reason": ("manual_override" if winner["source"] == "manual-override"
                           else reason),
            })
    return winner["value"], conflicts


def materially_differs(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a) != str(b)
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a != b
    denom = max(abs(fa), abs(fb))
    if denom == 0:
        return fa != fb
    return abs(fa - fb) / denom > REL_TOL


def src_name(key):
    return "manual override (scripts/overrides.json)" if key == "manual-override" \
        else SOURCES.get(key, {}).get("source_name", key)


# ----------------------------------------------------------------------------
# readers
# ----------------------------------------------------------------------------
bodies: dict = {}


def get_or_create(name, parent=None):
    bid = slugify(name)
    if bid not in bodies:
        b = Body(bid, name)
        b.parent_id = slugify(parent) if parent else None
        bodies[bid] = b
    return bodies[bid]


def read_helios_seed():
    manifest = json.loads((HELIOS / "bodies" / "manifest.json").read_text())
    for entry in manifest:
        path = HELIOS / "bodies" / entry
        if not path.exists():
            print(f"  ! missing {entry}, skipped", file=sys.stderr)
            continue
        data = json.loads(path.read_text())
        for item in (data if isinstance(data, list) else [data]):
            ingest_seed_item(item)
    print(f"  Helios seed bodies: {len(bodies)}")


def ingest_seed_item(item: dict):
    name = item.get("name")
    if not name:
        return
    b = get_or_create(name, item.get("parent"))
    S = "helios-seed"
    orbit = item.get("orbit", {}) or {}
    sma_au = num(orbit.get("semi_major_axis_au"))
    ecc = num(orbit.get("eccentricity"))
    inc = num(orbit.get("inclination_deg"))

    bid = b.id
    if bid == "sun":
        b.classification = "star"
    elif bid in MAJOR:
        b.classification = "major-planet"
    elif bid in DWARFS:
        b.classification = "dwarf-planet"
        b.parent_id = b.parent_id or "sun"
    elif bid in CENTAURS:
        b.classification = "centaur"
        b.parent_id = b.parent_id or "sun"
    elif isinstance(item.get("classification"), str) and item["classification"] in OUTER_CLASS:
        b.classification = OUTER_CLASS[item["classification"]]
        b.parent_id = b.parent_id or "sun"
    elif b.parent_id:
        b.classification = classify_moon(inc, ecc)
    else:
        b.classification = "tno"
        b.parent_id = "sun"
    if bid in MAJOR or bid == "sun":
        b.parent_id = "sun" if bid in MAJOR else None

    b.system = SYSTEM_MAP.get(b.parent_id or bid, "Solar System")

    r = item.get("render", {}) or {}
    if r.get("color") is not None:
        b.render["color_hex"] = color_hex(r["color"])
    if r.get("radius") is not None:
        b.render["radius"] = num(r["radius"])

    for al in item.get("aliases", []) or []:
        if al not in b.aliases:
            b.aliases.append(al)

    rk = item.get("radius_km")
    if rk is not None:
        b.add("radius_km", num(rk), S, raw=rk)
    m = item.get("mass")
    if isinstance(m, dict) and m.get("value") is not None:
        b.add("mass_kg", num(m["value"]), S, raw=m["value"])
    elif isinstance(m, (int, float)):
        b.add("mass_kg", float(m), S, raw=m)
    et = item.get("effective_temperature")
    if isinstance(et, dict) and et.get("value") is not None:
        b.add("mean_temperature_k", num(et["value"]), S, raw=et["value"])
    if isinstance(item.get("classification"), dict):
        st = item["classification"].get("spectral_type")
        if st:
            b.meta["spectral_type"] = st

    if sma_au:
        b.add("semi_major_axis_au", sma_au, S, raw=orbit.get("semi_major_axis_au"))
        b.add("semi_major_axis_km", sma_au * AU_KM, S, raw=orbit.get("semi_major_axis_au"))
    if ecc is not None:
        b.add("eccentricity", ecc, S, raw=orbit.get("eccentricity"))
    if inc is not None:
        b.add("inclination_deg", inc, S, raw=orbit.get("inclination_deg"))
    for f in ("longitude_ascending_node_deg", "mean_longitude_deg"):
        v = num(orbit.get(f))
        if v is not None:
            b.add(f, v, S, raw=orbit.get(f))
    lan = num(orbit.get("longitude_ascending_node_deg"))
    lp = num(orbit.get("longitude_periapsis_deg"))
    if lan is not None and lp is not None:
        b.add("argument_periapsis_deg", (lp - lan) % 360.0, S,
              raw=orbit.get("longitude_periapsis_deg"))
    rates = orbit.get("rates", {}) or {}
    if rates:
        b.rates = {k: num(v) for k, v in rates.items() if num(v) is not None}
        rate = num(rates.get("mean_longitude_deg"))
        if rate:
            b.add("orbital_period_days", 360 * 36525 / rate, S,
                  raw=rates.get("mean_longitude_deg"))
    if item.get("discovery_year"):
        b.add("discovery_year", int(item["discovery_year"]), S, raw=item["discovery_year"])
    if item.get("discoverer"):
        b.add("discoverer", item["discoverer"], S, raw=item["discoverer"])


def read_tier1():
    for bid, fields in TIER1.items():
        if bid not in bodies:
            continue
        b = bodies[bid]
        S = "static-jpl-iau"
        for f, v in fields.items():
            if v is None:
                continue
            if f == "discoverer":
                b.add(f, v, S, raw=v)
            elif f == "discovery_year":
                b.add(f, int(v), S, raw=v)
            elif f == "radius_uncertainty_km":
                continue  # attached below to radius candidate
            else:
                b.add(f, float(v) if isinstance(v, (int, float)) else v, S, raw=v)
        unc = fields.get("radius_uncertainty_km")
        for c in b.cands.get("radius_km", []):
            if c["source"] == S and unc is not None:
                c["uncertainty"] = float(unc)
    print(f"  Tier-1 reference rows applied: {len(TIER1)}")


def read_csv1():
    path = HELIOS / "db" / "Moons_of_Saturn_1.csv"
    if not path.exists():
        return
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    n = 0
    S = "saturn-csv1"
    for row in rows[1:]:
        if len(row) < 5 or not row[0].strip():
            continue
        name = clean_name(row[0])
        b = get_or_create(name, "saturn")
        b.classification = b.classification or "regular-moon"
        b.system = "Saturnian System"
        diam = num(str(row[1]).split("\n")[0])
        if diam:
            b.add("radius_km", diam / 2, S, raw=row[1])
        mass = num_sci(str(row[2]).split("\n")[0])
        if mass:
            b.add("mass_kg", mass, S, raw=row[2])
        sma = num(str(row[3]).split("\n")[0])
        if sma:
            b.add("semi_major_axis_km", sma, S, raw=row[3])
            b.add("semi_major_axis_au", sma / AU_KM, S, raw=row[3])
        per = num(str(row[4]).split("\n")[0])
        if per:
            b.add("orbital_period_days", per, S, raw=row[4])
        n += 1
    print(f"  Saturn CSV-1 rows: {n}")


def read_csv3():
    path = HELIOS / "db" / "Moons_of_Saturn_3.csv"
    if not path.exists():
        return
    # csv.reader handles quoted embedded newlines natively — no pre-joining
    # (joining would fuse row boundaries and silently drop bodies).
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    n = 0
    S = "saturn-csv3"
    for row in rows[1:]:
        if len(row) < 8:
            continue
        name = clean_name(row[1])
        if not name or name in ("—", "-") or "moonlet" in name.lower():
            continue
        label = row[0].strip().strip("—-")
        b = get_or_create(name, "saturn")
        b.system = "Saturnian System"
        sma_km = num(row[7])
        sma_au = sma_km / AU_KM if sma_km else None
        inc = num(row[9]) if len(row) > 9 else None
        ecc = num(row[10]) if len(row) > 10 else None
        group = row[11] if len(row) > 11 else ""
        b.classification = classify_moon(inc, ecc, group)
        if label:
            yr = num(row[13]) or num(row[12])
            b.designations.append({"designation": f"Saturn {label}",
                                   "since": int(yr) if yr else None,
                                   "kind": "roman-numeral"})
        if re.match(r"^S/\d{4}\s+S\s+\d+$", name):
            yr = num(row[12])
            b.designations.append({"designation": name,
                                   "since": int(yr) if yr else None,
                                   "kind": "provisional"})

        diam, dims, unc = parse_diameter_cell(row[5] if len(row) > 5 else "")
        if dims:
            b.meta["dimensions"] = dims
        if diam:
            b.add("radius_km", diam / 2, S, raw=row[5], uncertainty=(unc / 2 if unc else None))
        if len(row) > 6 and row[6].strip() not in ("", "?", "—", "-"):
            mv = num(row[6])
            if mv:
                b.add("mass_kg", mv * 1e15, S, raw=row[6])
        if sma_km:
            b.add("semi_major_axis_km", sma_km, S, raw=row[7])
            b.add("semi_major_axis_au", sma_au, S, raw=row[7])
        if len(row) > 8 and num(row[8]) is not None:
            b.add("orbital_period_days", abs(num(row[8])), S, raw=row[8])
        if inc is not None:
            b.add("inclination_deg", inc, S, raw=row[9] if len(row) > 9 else None)
        if ecc is not None:
            b.add("eccentricity", ecc, S, raw=row[10] if len(row) > 10 else None)
        if len(row) > 4 and row[4].strip() not in ("", "—", "-", "–"):
            h = num(row[4])
            if h is not None:
                b.add("absolute_magnitude_h", h, S, raw=row[4])
        if len(row) > 12 and num(row[12]):
            b.add("discovery_year", int(num(row[12])), S, raw=row[12])
        if len(row) > 13 and num(row[13]):
            b.add("announcement_year", int(num(row[13])), S, raw=row[13])
        if len(row) > 14 and row[14].strip() not in ("", "—", "-"):
            b.add("discoverer", " ".join(row[14].split()), S, raw=row[14])
        n += 1
    print(f"  Saturn CSV-3 rows: {n}")


def read_csv4():
    path = HELIOS / "db" / "Moons_of_Saturn_4.csv"
    if not path.exists():
        return
    # csv.reader handles quoted embedded newlines natively — no pre-joining.
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    n = 0
    S = "saturn-csv4"
    for row in rows[1:]:
        if len(row) < 7:
            continue
        name_raw = clean_name(row[0])
        if not name_raw or "moonlet" in name_raw.lower():
            continue  # aggregate class, not a body
        names = [name_raw]
        if " and " in name_raw:  # "S/2004 S 3 and S 4" → two bodies
            parts = [p.strip() for p in name_raw.split(" and ")]
            base = re.match(r"^(S/\d{4})", parts[0])
            names = [parts[0]] + [
                f"{base.group(1)} {p}" if base and not p.startswith("S/") else p
                for p in parts[1:]]
        m = re.search(r"(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)", row[2] if len(row) > 2 else "")
        rng = ((float(m.group(1)) + float(m.group(2))) / 4,
               (float(m.group(2)) - float(m.group(1))) / 4) if m else (None, None)
        sma = num(row[3]) if len(row) > 3 else None
        per = abs(num(row[4])) if len(row) > 4 and num(row[4]) else None
        disc = int(num(row[6])) if len(row) > 6 and num(row[6]) else None
        for nm in names:
            b = get_or_create(nm, "saturn")
            b.system = "Saturnian System"
            b.classification = b.classification or "regular-moon"
            if re.match(r"^S/\d{4}\s+S\s+\d+$", nm):
                b.designations.append({"designation": nm, "since": disc, "kind": "provisional"})
            if rng[0]:
                b.add("radius_km", rng[0], S, raw=row[2], uncertainty=rng[1])
            if sma:
                b.add("semi_major_axis_km", sma, S, raw=row[3])
                b.add("semi_major_axis_au", sma / AU_KM, S, raw=row[3])
            if per:
                b.add("orbital_period_days", per, S, raw=row[4])
            if disc:
                b.add("discovery_year", disc, S, raw=row[6])
            n += 1
    print(f"  Saturn CSV-4 bodies: {n}")


def read_jupiter_csv2():
    """Full Jupiter-moon table. Same family as Saturn-3 but Group is last
    (index 14) and group glyphs trail the name ('Io♠')."""
    path = HELIOS / "db" / "Moons_of_Jupiter_2.csv"
    if not path.exists():
        return
    # csv.reader handles quoted embedded newlines natively — no pre-joining.
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    n = 0
    S = "jupiter-csv2"
    for row in rows[1:]:
        if len(row) < 9:
            continue
        name = clean_name(row[1])
        if not name or name in ("—", "-"):
            continue
        label = row[0].strip().strip("—-")
        b = get_or_create(name, "jupiter")
        b.system = "Jovian System"
        inc = num(row[9]) if len(row) > 9 else None
        ecc = num(row[10]) if len(row) > 10 else None
        group = row[14].strip() if len(row) > 14 else ""
        b.classification = classify_moon(inc, ecc, group)
        if label:
            yr = num(row[12]) or num(row[11])
            b.designations.append({"designation": f"Jupiter {label}",
                                   "since": int(yr) if yr else None,
                                   "kind": "roman-numeral"})
        if re.match(r"^S/\d{4}\s+J\s+\d+$", name):
            yr = num(row[11])
            b.designations.append({"designation": name,
                                   "since": int(yr) if yr else None,
                                   "kind": "provisional"})

        diam, dims, unc = parse_diameter_cell(row[5] if len(row) > 5 else "")
        if dims:
            b.meta["dimensions"] = dims
        if diam:
            b.add("radius_km", diam / 2, S, raw=row[5], uncertainty=(unc / 2 if unc else None))
        if len(row) > 6 and row[6].strip() not in ("", "?", "—", "-"):
            mv = num(row[6])
            if mv:
                b.add("mass_kg", mv * 1e15, S, raw=row[6])
        sma_km = num(row[7]) if len(row) > 7 else None
        if sma_km:
            b.add("semi_major_axis_km", sma_km, S, raw=row[7])
            b.add("semi_major_axis_au", sma_km / AU_KM, S, raw=row[7])
        if len(row) > 8 and num(row[8]) is not None:
            b.add("orbital_period_days", abs(num(row[8])), S, raw=row[8])
        if inc is not None:
            b.add("inclination_deg", inc, S, raw=row[9])
        if ecc is not None:
            b.add("eccentricity", ecc, S, raw=row[10])
        if len(row) > 4 and row[4].strip() not in ("", "—", "-", "–"):
            h = num(row[4])
            if h is not None:
                b.add("absolute_magnitude_h", h, S, raw=row[4])
        if len(row) > 11 and num(row[11]):
            b.add("discovery_year", int(num(row[11])), S, raw=row[11])
        if len(row) > 12 and num(row[12]):
            b.add("announcement_year", int(num(row[12])), S, raw=row[12])
        if len(row) > 13 and row[13].strip() not in ("", "—", "-"):
            b.add("discoverer", " ".join(row[13].split()), S, raw=row[13])
        n += 1
    print(f"  Jupiter CSV-2 rows: {n} (CSV-1 is a group legend, no bodies)")


def read_jupiter_csv3():
    """Surface radiation (rem/day) for the Galilean moons. Earth rows are
    reference context only and are skipped."""
    path = HELIOS / "db" / "Moons_of_Jupiter_3.csv"
    if not path.exists():
        return
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    n = 0
    S = "jupiter-csv3"
    for row in rows[1:]:
        if len(row) < 2:
            continue
        name = clean_name(row[0])
        if not name or name.lower().startswith("earth"):
            continue
        bid = slugify(name)
        if bid not in bodies:
            continue
        v = num(row[1])
        if v is not None:
            bodies[bid].add("surface_radiation_rem_day", v, S, raw=row[1])
            n += 1
    print(f"  Jupiter CSV-3 radiation rows: {n}")


def apply_curated():
    for bid, als in ALIASES.items():
        if bid in bodies:
            for a in als:
                if a not in bodies[bid].aliases:
                    bodies[bid].aliases.append(a)
    for bid, ds in CURATED_DESIGNATIONS.items():
        if bid in bodies:
            have = {d["designation"] for d in bodies[bid].designations}
            for d in ds:
                if d["designation"] not in have:
                    bodies[bid].designations.append(d)
    if "saturn" in bodies:
        bodies["saturn"].meta["rings"] = SATURN_RINGS


def apply_overrides():
    if not OVERRIDES_PATH.exists():
        return 0
    data = json.loads(OVERRIDES_PATH.read_text())
    n = 0
    for ov in data.get("overrides", []):
        bid = slugify(ov["id"])
        if bid not in bodies:
            print(f"  ! override target missing: {ov['id']}", file=sys.stderr)
            continue
        b = bodies[bid]
        field, value = ov["field"], ov["value"]
        if field == "classification":
            old = b.classification
            b.classification = value
            if old == value:
                continue  # group rule already agrees — no conflict to log
            b.meta.setdefault("override_conflicts", []).append({
                "field": field, "chosen_value": value,
                "chosen_source": src_name("manual-override"),
                "rejected_value": old, "rejected_source": "automated ingest rule",
                "reason": f"manual_override: {ov.get('reason', '')}",
            })
        else:
            b.cands.setdefault(field, []).append({
                "value": value, "source": "manual-override",
                "retrieved": "9999-12-31", "uncertainty": -1.0,
                "sigfigs": 99,
            })
            # uncertainty -1.0 guarantees the override wins the merge
        n += 1
    print(f"  Overrides applied: {n}")
    return n


# ----------------------------------------------------------------------------
# finalize + write
# ----------------------------------------------------------------------------
COLUMNS = ["id", "name", "classification", "parent_id", "system", "superseded_by",
           "designations_json", "aliases_json", "radius_km", "radius_uncertainty_km",
           "equatorial_radius_km", "polar_radius_km", "dimensions_json", "mass_kg",
           "gm_km3_s2", "density_g_cm3", "surface_gravity_m_s2", "escape_velocity_km_s",
           "rotation_period_h", "axial_tilt_deg", "geometric_albedo", "bond_albedo",
           "spectral_type", "absolute_magnitude_h", "apparent_magnitude_v",
           "mean_temperature_k", "atmosphere_summary", "surface_radiation_rem_day",
           "semi_major_axis_au",
           "semi_major_axis_km", "periapsis_au", "apoapsis_au", "eccentricity",
           "inclination_deg", "longitude_ascending_node_deg", "argument_periapsis_deg",
           "mean_anomaly_deg", "mean_longitude_deg", "orbital_period_days",
           "orbital_period_years", "orbital_velocity_km_s", "epoch_jd", "rates_json",
           "discovery_year", "announcement_year", "discoverer", "discovery_site",
           "naming_origin", "sources_json", "conflicts_json", "confidence_score",
           "render_color_hex", "render_radius", "rings_json",
           "created_at", "updated_at"]

STR_FIELDS = {"discoverer", "spectral_type"}


def finalize_body(b: Body):
    row = {c: None for c in COLUMNS}
    row.update({"id": b.id, "name": b.name, "classification": b.classification,
                "parent_id": b.parent_id, "system": b.system,
                "designations_json": json.dumps(sorted(
                    b.designations, key=lambda d: (d.get("since") or 0, d["designation"]))),
                "aliases_json": json.dumps(sorted(b.aliases)),
                "dimensions_json": json.dumps(b.meta.get("dimensions", [])),
                "rates_json": json.dumps(b.rates, sort_keys=True),
                "rings_json": json.dumps(b.meta.get("rings", {}), sort_keys=True),
                "render_color_hex": b.render.get("color_hex"),
                "render_radius": b.render.get("radius"),
                "spectral_type": b.meta.get("spectral_type"),
                "epoch_jd": J2000, "created_at": SNAPSHOT_TS, "updated_at": SNAPSHOT_TS})
    conflicts = list(b.meta.get("override_conflicts", []))
    fields_used: dict = {}
    for field in sorted(b.cands):
        cands = b.cands[field]
        if field in STR_FIELDS:
            vals = sorted({str(c["value"]) for c in cands})
            winner = vals[0]
            for v in vals[1:]:
                conflicts.append({"field": field, "chosen_value": winner,
                                  "chosen_source": src_name(cands[0]["source"]),
                                  "rejected_value": v,
                                  "rejected_source": src_name(cands[-1]["source"]),
                                  "reason": "first-listed"})
            row[field] = winner
        else:
            w, conf = merge_field(field, cands)
            row[field] = (int(w) if field in ("discovery_year", "announcement_year")
                          and float(w) == int(w) else w)
            conflicts.extend(conf)
        for c in cands:
            if c["source"] != "manual-override":
                fields_used.setdefault(c["source"], set()).add(field)
    rc = b.cands.get("radius_km", [])
    if rc:
        wval = row["radius_km"]
        for c in rc:
            if c["value"] == wval and c["uncertainty"] is not None and c["uncertainty"] >= 0:
                row["radius_uncertainty_km"] = c["uncertainty"]
                break
    sma_au, ecc = row["semi_major_axis_au"], row["eccentricity"]
    if sma_au and row["semi_major_axis_km"] is None:
        row["semi_major_axis_km"] = sma_au * AU_KM
    if row["semi_major_axis_km"] and not sma_au:
        row["semi_major_axis_au"] = row["semi_major_axis_km"] / AU_KM
        sma_au = row["semi_major_axis_au"]
    if sma_au and ecc is not None:
        row["periapsis_au"] = sma_au * (1 - ecc)
        row["apoapsis_au"] = sma_au * (1 + ecc)
    if row["orbital_period_days"]:
        row["orbital_period_years"] = row["orbital_period_days"] / 365.25
    sources = []
    for sk in sorted(fields_used):
        s = SOURCES[sk]
        sources.append({"source_name": s["source_name"], "source_url": s["source_url"],
                        "retrieved_date": s["retrieved_date"],
                        "fields_provided": sorted(fields_used[sk])})
    if any(c["source"] == "manual-override" for cl in b.cands.values() for c in cl):
        sources.append({"source_name": src_name("manual-override"),
                        "source_url": "", "retrieved_date": SNAPSHOT_TS[:10],
                        "fields_provided": sorted({f for f, cl in b.cands.items()
                                                   for c in cl if c["source"] == "manual-override"})})
    row["sources_json"] = json.dumps(sources, sort_keys=True)
    conflicts.sort(key=lambda c: (c["field"], str(c["rejected_value"])))
    row["conflicts_json"] = json.dumps(conflicts)
    row["confidence_score"] = round(max(0.5, 1.0 - 0.05 * len(conflicts)), 2)
    return row


def build_db(reset=False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA_PATH.read_text())
    ordered = sorted(bodies, key=lambda bid: (
        0 if bid == "sun" else
        1 if bid in MAJOR or bodies[bid].parent_id in (None, "sun") else 2, bid))
    for bid in ordered:
        row = finalize_body(bodies[bid])
        db.execute(f"INSERT OR REPLACE INTO bodies ({', '.join(COLUMNS)}) "
                   f"VALUES ({', '.join('?' * len(COLUMNS))})",
                   [row[c] for c in COLUMNS])
    db.commit()
    return db


def print_stats(db):
    total = db.execute("SELECT COUNT(*) FROM bodies").fetchone()[0]
    conf = db.execute("SELECT COUNT(*) FROM bodies WHERE conflicts_json != '[]'").fetchone()[0]
    print(f"\nTotal bodies: {total}")
    print(f"Conflicts logged: {conf}")
    for cls, n in db.execute(
            "SELECT classification, COUNT(*) FROM bodies GROUP BY classification ORDER BY 2 DESC"):
        print(f"  {cls:<16} {n}")


def main():
    ap = argparse.ArgumentParser(description="HeliosDB ingestion pipeline")
    ap.add_argument("--reset", action="store_true", help="delete and rebuild helios.db")
    args = ap.parse_args()
    print("HeliosDB ingest — reading sources from", HELIOS)
    read_helios_seed()
    read_tier1()
    read_csv1()
    read_csv3()
    read_csv4()
    read_jupiter_csv2()
    read_jupiter_csv3()
    apply_curated()
    apply_overrides()
    print("Writing database...")
    db = build_db(args.reset)
    print_stats(db)
    db.close()
    print("Done.")


if __name__ == "__main__":
    main()
