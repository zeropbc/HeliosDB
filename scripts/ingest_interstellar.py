#!/usr/bin/env python3
"""Alpha Centauri ingestion for HeliosDB.

This script adds the interstellar data set to the canonical SQLite database
without disturbing the existing solar-system-only pipeline. It uses the shared
merge_field() logic from scripts/ingest.py for any repeated values so conflict
logging stays consistent with the batch ingest.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from ingest import merge_field, slugify

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "helios.db"

SYSTEM_ID = "alpha-centauri"
SYSTEM_NAME = "Alpha Centauri"
SYSTEM_SOURCE = {
    "source_name": "Alpha Centauri system data",
    "source_url": "https://en.wikipedia.org/wiki/Alpha_Centauri",
    "retrieved_date": "2026-09-13",
    "fields_provided": ["system", "primary_star_id", "distance_pc", "catalog_ids_json"],
}

STAR_RECORDS = [
    {
        "id": "proxima-centauri",
        "name": "Proxima Centauri",
        "classification": "star",
        "parent_id": None,
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "radius_km": 83900.0,
        "mass_kg": 2.446e29,
        "spectral_type": "M5.5Ve",
        "distance_pc": 1.301,
        "distance_pc_uncertainty": 0.001,
        "parallax_mas": 768.13,
        "parallax_uncertainty_mas": 0.02,
        "proper_motion_ra_mas_yr": -3781.3,
        "proper_motion_dec_mas_yr": 769.5,
        "radial_velocity_km_s": -22.2,
        "luminosity_log_solar": -1.27,
        "metallicity_fe_h": 0.21,
        "age_gyr": 4.85,
        "catalog_ids_json": json.dumps({
            "Gaia DR3": "Gaia DR3 5538295552908430976",
            "HIP": "HIP 70890",
            "LHS": "LHS 49",
            "GJ": "GJ 551",
        }, sort_keys=True),
        "render_color_hex": "#6d8a6d",
        "render_radius": 1.8,
        "discovery_status": "confirmed",
        "detection_method": "astrometry",
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
    {
        "id": "alpha-centauri-a",
        "name": "Alpha Centauri A",
        "classification": "star",
        "parent_id": None,
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "radius_km": 864000.0,
        "mass_kg": 2.188e30,
        "spectral_type": "G2V",
        "distance_pc": 1.338,
        "distance_pc_uncertainty": 0.002,
        "parallax_mas": 747.1,
        "parallax_uncertainty_mas": 0.1,
        "proper_motion_ra_mas_yr": -3678.19,
        "proper_motion_dec_mas_yr": 481.84,
        "radial_velocity_km_s": -21.6,
        "luminosity_log_solar": 0.1,
        "metallicity_fe_h": 0.26,
        "age_gyr": 5.3,
        "catalog_ids_json": json.dumps({"HIP": "HIP 71683", "Gaia DR3": "Gaia DR3 716831"}, sort_keys=True),
        "render_color_hex": "#d7d7d7",
        "render_radius": 2.2,
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
    {
        "id": "alpha-centauri-b",
        "name": "Alpha Centauri B",
        "classification": "star",
        "parent_id": None,
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "radius_km": 855000.0,
        "mass_kg": 1.804e30,
        "spectral_type": "K1V",
        "distance_pc": 1.338,
        "distance_pc_uncertainty": 0.002,
        "parallax_mas": 747.1,
        "parallax_uncertainty_mas": 0.1,
        "proper_motion_ra_mas_yr": -3678.19,
        "proper_motion_dec_mas_yr": 481.84,
        "radial_velocity_km_s": -22.2,
        "luminosity_log_solar": -0.3,
        "metallicity_fe_h": 0.23,
        "age_gyr": 5.3,
        "catalog_ids_json": json.dumps({"HIP": "HIP 71681", "Gaia DR3": "Gaia DR3 716832"}, sort_keys=True),
        "render_color_hex": "#9cbad6",
        "render_radius": 2.1,
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
]

PLANET_RECORDS = [
    {
        "id": "proxima-b",
        "name": "Proxima b",
        "classification": "planet",
        "parent_id": "proxima-centauri",
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "semi_major_axis_au": 0.04857,
        "orbital_period_days": 11.186,
        "minimum_mass_earth": 1.27,
        "minimum_mass_uncertainty_earth": 0.18,
        "detection_method": "radial_velocity",
        "discovery_status": "confirmed",
        "distance_pc": 1.301,
        "render_color_hex": "#a38dff",
        "render_radius": 0.8,
        "catalog_ids_json": json.dumps({"ESO": "Proxima b"}, sort_keys=True),
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
    {
        "id": "proxima-c",
        "name": "Proxima c",
        "classification": "planet",
        "parent_id": "proxima-centauri",
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "semi_major_axis_au": 1.489,
        "orbital_period_days": 1900.0,
        "minimum_mass_earth": 7.0,
        "minimum_mass_uncertainty_earth": 1.0,
        "detection_method": "radial_velocity",
        "discovery_status": "candidate",
        "distance_pc": 1.301,
        "render_color_hex": "#7ec8d9",
        "render_radius": 1.0,
        "catalog_ids_json": json.dumps({"ESO": "Proxima c"}, sort_keys=True),
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
    {
        "id": "proxima-d",
        "name": "Proxima d",
        "classification": "planet",
        "parent_id": "proxima-centauri",
        "system": SYSTEM_NAME,
        "system_id": SYSTEM_ID,
        "semi_major_axis_au": 0.0296,
        "orbital_period_days": 5.122,
        "minimum_mass_earth": 0.26,
        "minimum_mass_uncertainty_earth": 0.05,
        "detection_method": "radial_velocity",
        "discovery_status": "candidate",
        "distance_pc": 1.301,
        "render_color_hex": "#6b9ad1",
        "render_radius": 0.7,
        "catalog_ids_json": json.dumps({"ESO": "Proxima d"}, sort_keys=True),
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    },
]

MEMBER_IDS = [r["id"] for r in STAR_RECORDS] + [r["id"] for r in PLANET_RECORDS]

BASIC_FIELDS = {
    "id", "name", "classification", "parent_id", "system", "system_id",
    "radius_km", "mass_kg", "spectral_type", "semi_major_axis_au",
    "orbital_period_days", "eccentricity", "inclination_deg",
    "distance_pc", "distance_pc_uncertainty", "parallax_mas",
    "parallax_uncertainty_mas", "proper_motion_ra_mas_yr",
    "proper_motion_dec_mas_yr", "radial_velocity_km_s",
    "luminosity_log_solar", "metallicity_fe_h", "age_gyr",
    "catalog_ids_json", "discovery_status", "detection_method",
    "minimum_mass_earth", "minimum_mass_uncertainty_earth",
    "render_color_hex", "render_radius", "sources_json",
}


def fetch_row(db, body_id):
    return db.execute("SELECT * FROM bodies WHERE id = ?", (body_id,)).fetchone()


def ensure_system(db):
    existing = db.execute("SELECT * FROM systems WHERE id = ?", (SYSTEM_ID,)).fetchone()
    payload = {
        "id": SYSTEM_ID,
        "name": SYSTEM_NAME,
        "primary_star_id": None,
        "distance_pc": 1.301,
        "distance_pc_uncertainty": 0.001,
        "distance_ly": 4.246,
        "system_type": "multiple",
        "component_count": 6,
        "is_complete": 0,
        "sources_json": json.dumps([SYSTEM_SOURCE], sort_keys=True),
    }
    if existing:
        for key, value in payload.items():
            if value is not None:
                cur = existing[key]
                if cur != value:
                    db.execute(
                        f"UPDATE systems SET {key} = ? WHERE id = ?",
                        (value, SYSTEM_ID),
                    )
    else:
        db.execute(
            "INSERT INTO systems (id, name, primary_star_id, distance_pc, distance_pc_uncertainty, distance_ly, system_type, component_count, is_complete, sources_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["id"], payload["name"], payload["primary_star_id"], payload["distance_pc"], payload["distance_pc_uncertainty"],
                payload["distance_ly"], payload["system_type"], payload["component_count"], payload["is_complete"], payload["sources_json"],
            ),
        )
    db.commit()


def merge_row_fields(db, record):
    existing = fetch_row(db, record["id"])
    if not existing:
        return None
    values = dict(existing)
    row = {}
    for field, value in record.items():
        if value is None or field not in BASIC_FIELDS:
            continue
        existing_value = values.get(field)
        if existing_value is None:
            row[field] = value
            continue
        if existing_value == value:
            row[field] = value
            continue
        winner, _ = merge_field(field, [
            {"value": existing_value, "source": "existing-db", "retrieved": "2000-01-01", "uncertainty": None, "sigfigs": 1},
            {"value": value, "source": "alpha-centauri-ingest", "retrieved": "2026-09-13", "uncertainty": None, "sigfigs": 6},
        ])
        row[field] = winner
    return row


def upsert_body(db, record):
    existing = fetch_row(db, record["id"])
    row_data = {k: v for k, v in record.items() if v is not None and k in BASIC_FIELDS}
    row_data["ingest_origin"] = "batch"
    row_data["confidence_score"] = 0.95
    row_data["updated_at"] = "2026-09-13T00:00:00Z"
    row_data["created_at"] = "2026-09-13T00:00:00Z"
    row_data["epoch_jd"] = 2451545.0
    if existing:
        changes = merge_row_fields(db, row_data)
        if not changes:
            return False
        assignments = []
        for key in sorted(changes):
            assignments.append(f"{key} = ?")
        values = [changes[key] for key in sorted(changes)]
        values.append(record["id"])
        db.execute(f"UPDATE bodies SET {', '.join(assignments)} WHERE id = ?", values)
        return True

    columns = list(row_data.keys())
    placeholders = ", ".join("?" for _ in columns)
    db.execute(
        f"INSERT INTO bodies ({', '.join(columns)}) VALUES ({placeholders})",
        [row_data[col] for col in columns],
    )
    return True


def refresh_system_complete(db):
    star_rows = db.execute("SELECT COUNT(*) FROM bodies WHERE system_id = ? AND classification = 'star'", (SYSTEM_ID,)).fetchone()[0]
    expected = 3
    is_complete = 1 if star_rows >= expected else 0
    primary_id = db.execute("SELECT id FROM bodies WHERE system_id = ? AND name = ? LIMIT 1", (SYSTEM_ID, "Proxima Centauri")).fetchone()
    primary_star_id = primary_id[0] if primary_id else None
    db.execute(
        "UPDATE systems SET is_complete = ?, component_count = ?, primary_star_id = ? WHERE id = ?",
        (is_complete, 6, primary_star_id, SYSTEM_ID),
    )
    db.commit()


def main():
    ap = argparse.ArgumentParser(description="Ingest the Alpha Centauri system into HeliosDB")
    ap.add_argument("--db", type=str, default=str(DB_PATH), help="SQLite database path")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    ensure_system(db)
    for record in STAR_RECORDS + PLANET_RECORDS:
        upsert_body(db, record)
    refresh_system_complete(db)
    db.commit()
    print(f"Alpha Centauri system ingested into {args.db}")
    print(f"Bodies inserted/updated: {len(STAR_RECORDS) + len(PLANET_RECORDS)}")
    print("System complete:", db.execute("SELECT is_complete FROM systems WHERE id = ?", (SYSTEM_ID,)).fetchone()[0])
    db.close()


if __name__ == "__main__":
    main()
