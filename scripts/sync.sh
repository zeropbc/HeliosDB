#!/usr/bin/env bash
# HeliosDB manual sync — rebuilds everything and copies canonical JSON into Helios.
# Manual-trust phase: review diffs in BOTH repos before committing. No auto-commit.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "1/4 Rebuilding canonical database..."
python3 scripts/ingest.py --reset

echo "2/4 Exporting static JSON (canonical shape)..."
python3 scripts/export_static.py

echo "3/4 Generating static HTML pages..."
python3 scripts/export_pages.py

echo "4/4 Syncing canonical JSON into Helios (side-by-side, non-breaking)..."
# New filenames only — never overwrites the live manifest.json / hand-authored
# files the engine reads today. The renderer update will repoint the loader
# at bodies/data/ + manifest-canonical.json; old files retire after that.
HELIOS_DIR="../Helios/bodies/data"
mkdir -p "$HELIOS_DIR"
cp public/data/bodies/*.json "$HELIOS_DIR/"
cp public/data/index.json "$HELIOS_DIR/manifest-canonical.json"

echo "Sync complete. Review changes in both repos before committing."
