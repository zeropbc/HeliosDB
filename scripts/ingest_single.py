#!/usr/bin/env python3
"""Single-body ingestion helper.

Usage:
  python3 scripts/ingest_single.py body.json
  python3 scripts/ingest_single.py --watch new-bodies/

Single-ingested rows are intentionally ephemeral: they are wiped the next time
python3 scripts/ingest.py --reset rebuilds the database from its batch sources.
"""

import argparse
import json
import sqlite3
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "helios.db"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonicalize(record):
    if not isinstance(record, dict):
        raise ValueError("input JSON must be an object")
    flat = {}
    for key, value in record.items():
        if key in {"physical", "orbital", "discovery", "astrometry", "stellar", "render", "provenance", "catalog_ids"}:
            if isinstance(value, dict):
                flat.update(value)
        else:
            flat[key] = value
    return flat


def build_sources_json(input_path):
    return json.dumps([
        {
            "source_name": "manual single-body ingest",
            "source_url": str(input_path),
            "retrieved_date": "2026-09-13",
            "fields_provided": sorted({k for k in canonicalize(read_json(input_path)).keys() if k not in {"ingest_origin"}}),
        }
    ], sort_keys=True)


def normalize_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


def merge_conflict(existing, incoming, field):
    if existing is None or incoming is None:
        return existing if existing is not None else incoming
    if existing == incoming:
        return existing
    return existing


def upsert_single(db, json_path):
    record = canonicalize(read_json(json_path))
    body_id = record.get("id")
    if not body_id:
        raise ValueError(f"{json_path}: missing id")
    existing = db.execute("SELECT * FROM bodies WHERE id = ?", (body_id,)).fetchone()
    sources_json = build_sources_json(json_path)

    if existing:
        updates = []
        for field, value in record.items():
            if field in {"id", "created_at", "updated_at"}:
                continue
            if field in {"sources_json", "conflicts_json"}:
                continue
            existing_value = existing[field] if field in existing.keys() else None
            if value is None:
                continue
            if existing_value is None:
                updates.append((field, normalize_value(value)))
                continue
            chosen = merge_conflict(existing_value, value, field)
            if chosen != existing_value:
                updates.append((field, normalize_value(chosen)))
        # leave the record with same winner value as before, but record disagreement in conflicts_json
        base_conflicts = json.loads(existing["conflicts_json"] or "[]")
        new_conflicts = []
        for field, value in record.items():
            if field in {"id", "created_at", "updated_at", "sources_json", "conflicts_json"}:
                continue
            if field not in existing.keys():
                continue
            existing_value = existing[field]
            if existing_value is None:
                continue
            if existing_value != value and value is not None:
                new_conflicts.append({
                    "field": field,
                    "chosen_value": existing_value,
                    "chosen_source": "existing database row",
                    "rejected_value": value,
                    "rejected_source": "manual single-body ingest",
                    "reason": "manual_single_ingest",
                })
        if new_conflicts:
            base_conflicts.extend(new_conflicts)
            db.execute(
                "UPDATE bodies SET conflicts_json = ?, sources_json = ?, ingest_origin = 'single' WHERE id = ?",
                (json.dumps(base_conflicts, sort_keys=True), sources_json, body_id),
            )
        if updates:
            assignments = ", ".join(f"{field} = ?" for field, _ in updates)
            values = [v for _, v in updates] + [body_id]
            db.execute(f"UPDATE bodies SET {assignments}, ingest_origin = 'single', sources_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values + [sources_json, body_id])
        db.commit()
        return body_id

    row = {
        "id": body_id,
        "name": record.get("name") or body_id,
        "classification": record.get("classification") or "unknown",
        "parent_id": record.get("parent_id"),
        "system": record.get("system"),
        "system_id": record.get("system_id"),
        "ingest_origin": "single",
        "designations_json": json.dumps(record.get("designations", []) or []),
        "aliases_json": json.dumps(record.get("aliases", []) or []),
        "sources_json": sources_json,
        "conflicts_json": "[]",
        "confidence_score": 0.9,
        "created_at": "2026-09-13T00:00:00Z",
        "updated_at": "2026-09-13T00:00:00Z",
        "epoch_jd": 2451545.0,
    }
    for key in [
        "radius_km", "radius_uncertainty_km", "equatorial_radius_km", "polar_radius_km",
        "dimensions_json", "mass_kg", "gm_km3_s2", "density_g_cm3", "surface_gravity_m_s2",
        "escape_velocity_km_s", "rotation_period_h", "axial_tilt_deg", "geometric_albedo",
        "bond_albedo", "spectral_type", "absolute_magnitude_h", "apparent_magnitude_v",
        "mean_temperature_k", "atmosphere_summary", "surface_radiation_rem_day",
        "semi_major_axis_au", "semi_major_axis_km", "periapsis_au", "apoapsis_au",
        "eccentricity", "inclination_deg", "longitude_ascending_node_deg",
        "argument_periapsis_deg", "mean_anomaly_deg", "mean_longitude_deg",
        "orbital_period_days", "orbital_period_years", "orbital_velocity_km_s",
        "discovery_year", "announcement_year", "discoverer", "discovery_site",
        "naming_origin", "discovery_status", "detection_method", "minimum_mass_earth",
        "minimum_mass_uncertainty_earth", "parallax_mas", "parallax_uncertainty_mas",
        "parallax_epoch", "proper_motion_ra_mas_yr", "proper_motion_dec_mas_yr",
        "radial_velocity_km_s", "radial_velocity_uncertainty_km_s", "distance_pc",
        "distance_pc_uncertainty", "luminosity_log_solar", "metallicity_fe_h", "age_gyr",
        "catalog_ids_json", "render_color_hex", "render_radius", "rings_json",
    ]:
        if key in record:
            row[key] = normalize_value(record[key])
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    db.execute(f"INSERT INTO bodies ({', '.join(columns)}) VALUES ({placeholders})", [row[col] for col in columns])
    db.commit()
    return body_id


def process_file(db, file_path):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    body_id = upsert_single(db, path)
    print(f"ingested {body_id} from {path.name}")
    return body_id


def watch_dir(db, watch_dir):
    root = Path(watch_dir)
    root.mkdir(parents=True, exist_ok=True)
    processed = root / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        if path.parent != root:
            continue
        try:
            process_file(db, path)
            target = processed / path.name
            if target.exists():
                target.unlink()
            shutil.move(str(path), str(target))
            print(f"moved {path.name} -> {target}")
        except Exception as exc:
            print(f"failed {path}: {exc}", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Ingest a single canonical body JSON into HeliosDB. "
            "Single-ingested rows are intentionally ephemeral: they are wiped by "
            "python3 scripts/ingest.py --reset because reset rebuilds from batch sources only."
        )
    )
    ap.add_argument("path", nargs="?", help="body JSON file to ingest")
    ap.add_argument("--watch", dest="watch_dir", help="watch a directory for JSON files and move them to processed/ after success")
    ap.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    ap.add_argument("--reset", action="store_true", help="rebuild the database from batch sources only; single-ingested rows will be removed")
    args = ap.parse_args()

    if args.reset:
        import subprocess
        subprocess.run(["python3", str(ROOT / "scripts" / "ingest.py"), "--reset"], check=True)
        print("Reset complete; single-ingested rows are intentionally not preserved.")
        return

    if args.watch_dir:
        db = sqlite3.connect(args.db)
        db.execute("PRAGMA foreign_keys = ON")
        watch_dir(db, args.watch_dir)
        db.close()
        return

    if not args.path:
        ap.error("a JSON file path is required unless --watch or --reset is used")

    # explicit sentinel kept for testing and operator docs: ingest_origin='single'
    # marks non-authoritative rows that are removed when ingest.py --reset rebuilds.

    db = sqlite3.connect(args.db)
    db.execute("PRAGMA foreign_keys = ON")
    process_file(db, args.path)
    db.close()


if __name__ == "__main__":
    main()
