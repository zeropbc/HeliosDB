import importlib.util
import sqlite3
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = (ROOT / "schema" / "canonical.sql").read_text(encoding="utf-8")


class InterstellarSchemaAndToolingTests(unittest.TestCase):
    def test_schema_adds_systems_table_and_extended_body_fields(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS systems", SCHEMA)
        self.assertIn("primary_star_id", SCHEMA)
        self.assertIn("is_complete BOOLEAN NOT NULL DEFAULT 0", SCHEMA)
        self.assertIn("ALTER TABLE bodies ADD COLUMN system_id TEXT", SCHEMA)
        self.assertIn("ALTER TABLE bodies ADD COLUMN ingest_origin TEXT", SCHEMA)
        self.assertIn("ALTER TABLE bodies ADD COLUMN discovery_status TEXT", SCHEMA)
        self.assertIn("ALTER TABLE bodies ADD COLUMN minimum_mass_earth REAL", SCHEMA)

    def test_ingest_interstellar_script_exists_and_exposes_alpha_centauri(self):
        path = ROOT / "scripts" / "ingest_interstellar.py"
        self.assertTrue(path.exists(), "interstellar ingestion script should exist")
        module = importlib.util.spec_from_file_location("ingest_interstellar", path)
        self.assertIsNotNone(module)
        self.assertIn("alpha-centauri", path.read_text(encoding="utf-8").lower())

    def test_single_ingest_help_mentions_reset_behavior(self):
        path = ROOT / "scripts" / "ingest_single.py"
        self.assertTrue(path.exists(), "single-body ingestion script should exist")
        help_text = path.read_text(encoding="utf-8")
        self.assertIn("--reset", help_text)
        self.assertIn("ingest_origin='single'", help_text)


if __name__ == "__main__":
    unittest.main()
