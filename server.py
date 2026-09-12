#!/usr/bin/env python3
"""HeliosDB local dev API — DEVELOPMENT ONLY, never for production traffic.

stdlib http.server has no hardening/concurrency guarantees. It exists to test
query shapes against the local SQLite file before they are baked into the
static export (scripts/export_static.py).

Endpoints:
  GET /api/v1/bodies?q=&class=&parent=&sort=&limit=50&offset=0
  GET /api/v1/bodies/<id>            (resolves id_redirects)
  GET /api/v1/systems/<parent_id>
  GET /api/v1/export/helios          (Helios-engine shaped dump)
  GET /api/v1/stats
Also serves public/ statically for local frontend dev.
"""

import argparse
import json
import os
import sqlite3
import urllib.parse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "helios.db"
PUBLIC_DIR = ROOT / "public"

SORTABLE = {"name", "radius_km", "mass_kg", "semi_major_axis_au", "semi_major_axis_km",
            "eccentricity", "inclination_deg", "orbital_period_days", "discovery_year",
            "absolute_magnitude_h", "confidence_score"}


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def row_to_dict(r):
    d = dict(r)
    for k in ("designations_json", "aliases_json", "dimensions_json", "rates_json",
              "sources_json", "conflicts_json", "rings_json"):
        d[k.replace("_json", "")] = json.loads(d.pop(k))
    return d


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def log_message(self, *args):
        pass  # quiet

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path == "/api/v1/bodies":
                return self.send_json(self.api_bodies(q))
            if u.path.startswith("/api/v1/bodies/"):
                return self.send_json(self.api_body(u.path.rsplit("/", 1)[-1]))
            if u.path.startswith("/api/v1/systems/"):
                return self.send_json(self.api_system(u.path.rsplit("/", 1)[-1]))
            if u.path == "/api/v1/export/helios":
                return self.send_json(self.api_export())
            if u.path == "/api/v1/stats":
                return self.send_json(self.api_stats())
        except KeyError as e:
            return self.send_json({"error": str(e)}, 404)
        if u.path.startswith("/api/"):
            return self.send_json({"error": "unknown endpoint"}, 404)
        return super().do_GET()

    # -- endpoints ---------------------------------------------------------
    def api_bodies(self, q):
        con = db()
        where, params = [], []
        if q.get("q"):
            terms = [t + "*" for t in q["q"].split()]
            where.append("bodies_fts MATCH ?")
            params.append(" ".join(terms))
            join = "JOIN bodies_fts ON bodies_fts.rowid = bodies.rowid"
        else:
            join = ""
        if q.get("class"):
            where.append("classification = ?")
            params.append(q["class"])
        if q.get("parent"):
            where.append("parent_id = ?")
            params.append(q["parent"])
        sort = q.get("sort", "name") if q.get("sort", "name") in SORTABLE else "name"
        limit = min(int(q.get("limit", 50)), 500)
        offset = max(int(q.get("offset", 0)), 0)
        sql = f"SELECT bodies.* FROM bodies {join}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        total = con.execute(f"SELECT COUNT(*) FROM ({sql})",
                            params).fetchone()[0]
        sql += f" ORDER BY {sort} LIMIT ? OFFSET ?"
        rows = con.execute(sql, params + [limit, offset]).fetchall()
        con.close()
        return {"total": total, "limit": limit, "offset": offset,
                "results": [row_to_dict(r) for r in rows]}

    def api_body(self, bid):
        con = db()
        r = con.execute("SELECT * FROM bodies WHERE id = ?", (bid,)).fetchone()
        if r is None:
            red = con.execute("SELECT new_id FROM id_redirects WHERE old_id = ?",
                              (bid,)).fetchone()
            con.close()
            if red:
                return self.api_body(red["new_id"])
            raise KeyError(f"no body '{bid}'")
        con.close()
        return row_to_dict(r)

    def api_system(self, parent_id):
        con = db()
        parent = con.execute("SELECT * FROM bodies WHERE id = ?",
                             (parent_id,)).fetchone()
        if parent is None:
            con.close()
            raise KeyError(f"no body '{parent_id}'")
        moons = con.execute("SELECT * FROM bodies WHERE parent_id = ? ORDER BY "
                            "semi_major_axis_km", (parent_id,)).fetchall()
        con.close()
        return {"parent": row_to_dict(parent),
                "satellites": [row_to_dict(r) for r in moons]}

    def api_export(self):
        """Helios-engine shaped dump: name/orbit/render per body."""
        con = db()
        out = []
        for r in con.execute("SELECT * FROM bodies ORDER BY id"):
            d = dict(r)
            out.append({
                "name": d["name"],
                "parent": d["parent_id"],
                "classification": d["classification"],
                "radius_km": d["radius_km"],
                "render": {"color": d["render_color_hex"], "radius": d["render_radius"]},
                "orbit": {
                    "semi_major_axis_au": d["semi_major_axis_au"],
                    "eccentricity": d["eccentricity"],
                    "inclination_deg": d["inclination_deg"],
                    "longitude_ascending_node_deg": d["longitude_ascending_node_deg"],
                    "mean_longitude_deg": d["mean_longitude_deg"],
                    "orbital_period_days": d["orbital_period_days"],
                },
                "sources": [s["source_name"] for s in json.loads(d["sources_json"])],
            })
        con.close()
        return {"count": len(out), "bodies": out}

    def api_stats(self):
        con = db()
        total = con.execute("SELECT COUNT(*) FROM bodies").fetchone()[0]
        by_class = dict(con.execute(
            "SELECT classification, COUNT(*) FROM bodies GROUP BY classification"))
        conflicts = con.execute(
            "SELECT COUNT(*) FROM bodies WHERE conflicts_json != '[]'").fetchone()[0]
        con.close()
        return {"total_bodies": total, "by_classification": by_class,
                "bodies_with_conflicts": conflicts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    args = ap.parse_args()
    if not DB_PATH.exists():
        raise SystemExit(f"error: {DB_PATH} missing — run scripts/ingest.py first")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port),
                              partial(Handler))
    print(f"HeliosDB dev API on http://127.0.0.1:{args.port} (DEV ONLY)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
