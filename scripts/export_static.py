#!/usr/bin/env python3
"""HeliosDB static export — flattens data/helios.db into public/data/ JSON.

This is the actual production artifact: GitHub Pages serves these files
directly, no server required. Re-run after ingest.py on every data update.

  public/data/index.json        — [{id, name, aliases, classification, parent_id}]
  public/data/bodies/<id>.json  — full canonical record per body
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "helios.db"
OUT_DIR = ROOT / "data"
BODIES_DIR = OUT_DIR / "bodies"

PHYSICAL = ["radius_km", "radius_uncertainty_km", "equatorial_radius_km",
            "polar_radius_km", "dimensions_json", "mass_kg", "gm_km3_s2",
            "density_g_cm3", "surface_gravity_m_s2", "escape_velocity_km_s",
            "rotation_period_h", "axial_tilt_deg", "geometric_albedo", "bond_albedo",
            "spectral_type", "absolute_magnitude_h", "apparent_magnitude_v",
            "mean_temperature_k", "atmosphere_summary", "surface_radiation_rem_day"]
ORBITAL = ["semi_major_axis_au", "semi_major_axis_km", "periapsis_au", "apoapsis_au",
           "eccentricity", "inclination_deg", "longitude_ascending_node_deg",
           "argument_periapsis_deg", "mean_anomaly_deg", "mean_longitude_deg",
           "orbital_period_days", "orbital_period_years", "orbital_velocity_km_s",
           "epoch_jd", "rates_json"]
DISCOVERY = ["discovery_year", "announcement_year", "discoverer",
             "discovery_site", "naming_origin", "discovery_status",
             "detection_method", "minimum_mass_earth",
             "minimum_mass_uncertainty_earth"]
ASTROMETRY = ["parallax_mas", "parallax_uncertainty_mas", "parallax_epoch",
             "proper_motion_ra_mas_yr", "proper_motion_dec_mas_yr",
             "radial_velocity_km_s", "radial_velocity_uncertainty_km_s",
             "distance_pc", "distance_pc_uncertainty"]
STELLAR = ["luminosity_log_solar", "metallicity_fe_h", "age_gyr"]


def dump(obj):
    return json.dumps(obj, sort_keys=True, indent=1)


def main():
    if not DB_PATH.exists():
        sys.exit(f"error: {DB_PATH} missing — run scripts/ingest.py first")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM bodies ORDER BY id").fetchall()
    BODIES_DIR.mkdir(parents=True, exist_ok=True)

    index = []
    written = set()
    for r in rows:
        d = dict(r)
        written.add(d["id"])
        index.append({"id": d["id"], "name": d["name"],
                      "aliases": json.loads(d["aliases_json"]),
                      "classification": d["classification"],
                      "parent_id": d["parent_id"]})
        body = {
            "id": d["id"], "name": d["name"],
            "classification": d["classification"],
            "parent_id": d["parent_id"], "system": d["system"],
            "system_id": d["system_id"],
            "ingest_origin": d["ingest_origin"],
            "designations": json.loads(d["designations_json"]),
            "aliases": json.loads(d["aliases_json"]),
            "physical": {k: (json.loads(d[k]) if k.endswith("_json") else d[k])
                         for k in PHYSICAL if d[k] is not None},
            "orbital": {k: (json.loads(d[k]) if k.endswith("_json") else d[k])
                        for k in ORBITAL if d[k] is not None},
            "discovery": {k: d[k] for k in DISCOVERY if d[k] is not None},
            "astrometry": {k: d[k] for k in ASTROMETRY if d[k] is not None},
            "stellar": {k: d[k] for k in STELLAR if d[k] is not None},
            "catalog_ids": json.loads(d["catalog_ids_json"]),
            "provenance": {"sources": json.loads(d["sources_json"]),
                           "conflicts": json.loads(d["conflicts_json"])},
            "render": {"color_hex": d["render_color_hex"],
                       "radius": d["render_radius"],
                       "rings": json.loads(d["rings_json"])},
            "confidence_score": d["confidence_score"],
            "superseded_by": d["superseded_by"],
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
        }
        (BODIES_DIR / f"{d['id']}.json").write_text(dump(body) + "\n")
    (OUT_DIR / "index.json").write_text(dump(index) + "\n")
    # sweep stale files (renames/deletes must not leave ghosts behind)
    stale = [p for p in BODIES_DIR.glob("*.json") if p.stem not in written]
    for p in stale:
        p.unlink()
    print(f"Exported {len(index)} bodies → {OUT_DIR}"
          + (f" (removed {len(stale)} stale)" if stale else ""))
    db.close()


if __name__ == "__main__":
    main()
