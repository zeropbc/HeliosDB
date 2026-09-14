-- HeliosDB Canonical Astronomical Database Schema v1.1
-- Source: Implementation Plan / User Review

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bodies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    classification TEXT NOT NULL,
    parent_id TEXT,
    system TEXT,
    superseded_by TEXT,

    designations_json TEXT NOT NULL DEFAULT '[]',
    aliases_json TEXT NOT NULL DEFAULT '[]',

    -- Physical
    radius_km REAL,
    radius_uncertainty_km REAL,
    equatorial_radius_km REAL,
    polar_radius_km REAL,
    dimensions_json TEXT NOT NULL DEFAULT '[]',
    mass_kg REAL,
    gm_km3_s2 REAL,
    density_g_cm3 REAL,
    surface_gravity_m_s2 REAL,
    escape_velocity_km_s REAL,
    rotation_period_h REAL,
    axial_tilt_deg REAL,
    geometric_albedo REAL,
    bond_albedo REAL,
    spectral_type TEXT,
    absolute_magnitude_h REAL,
    apparent_magnitude_v REAL,
    mean_temperature_k REAL,
    atmosphere_summary TEXT,
    surface_radiation_rem_day REAL,  -- surface radiation environment (rem/day); sparse

    -- Orbital
    semi_major_axis_au REAL,
    semi_major_axis_km REAL,
    periapsis_au REAL,
    apoapsis_au REAL,
    eccentricity REAL,
    inclination_deg REAL,
    longitude_ascending_node_deg REAL,
    argument_periapsis_deg REAL,
    mean_anomaly_deg REAL,
    mean_longitude_deg REAL,
    orbital_period_days REAL,
    orbital_period_years REAL,
    orbital_velocity_km_s REAL,
    epoch_jd REAL,
    rates_json TEXT NOT NULL DEFAULT '{}',

    -- Discovery
    discovery_year INTEGER,
    announcement_year INTEGER,
    discoverer TEXT,
    discovery_site TEXT,
    naming_origin TEXT,

    -- Provenance / conflicts (plan spec: array of objects)
    sources_json TEXT NOT NULL DEFAULT '[]',
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    confidence_score REAL NOT NULL DEFAULT 1.0,

    -- Render hints
    render_color_hex TEXT,
    render_radius REAL,
    rings_json TEXT NOT NULL DEFAULT '{}',

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(parent_id) REFERENCES bodies(id) ON DELETE SET NULL,
    FOREIGN KEY(superseded_by) REFERENCES bodies(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS systems (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    primary_star_id TEXT,
    distance_pc REAL,
    distance_pc_uncertainty REAL,
    distance_ly REAL,
    system_type TEXT,
    component_count INTEGER,
    is_complete BOOLEAN NOT NULL DEFAULT 0,
    sources_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(primary_star_id) REFERENCES bodies(id) ON DELETE SET NULL
);

ALTER TABLE bodies ADD COLUMN system_id TEXT REFERENCES systems(id) ON DELETE SET NULL;
ALTER TABLE bodies ADD COLUMN ingest_origin TEXT NOT NULL DEFAULT 'batch';
ALTER TABLE bodies ADD COLUMN parallax_mas REAL;
ALTER TABLE bodies ADD COLUMN parallax_uncertainty_mas REAL;
ALTER TABLE bodies ADD COLUMN parallax_epoch REAL;
ALTER TABLE bodies ADD COLUMN proper_motion_ra_mas_yr REAL;
ALTER TABLE bodies ADD COLUMN proper_motion_dec_mas_yr REAL;
ALTER TABLE bodies ADD COLUMN radial_velocity_km_s REAL;
ALTER TABLE bodies ADD COLUMN radial_velocity_uncertainty_km_s REAL;
ALTER TABLE bodies ADD COLUMN distance_pc REAL;
ALTER TABLE bodies ADD COLUMN distance_pc_uncertainty REAL;
ALTER TABLE bodies ADD COLUMN luminosity_log_solar REAL;
ALTER TABLE bodies ADD COLUMN metallicity_fe_h REAL;
ALTER TABLE bodies ADD COLUMN age_gyr REAL;
ALTER TABLE bodies ADD COLUMN catalog_ids_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE bodies ADD COLUMN discovery_status TEXT;
ALTER TABLE bodies ADD COLUMN detection_method TEXT;
ALTER TABLE bodies ADD COLUMN minimum_mass_earth REAL;
ALTER TABLE bodies ADD COLUMN minimum_mass_uncertainty_earth REAL;

CREATE TABLE IF NOT EXISTS id_redirects (
    old_id TEXT PRIMARY KEY,
    new_id TEXT NOT NULL,
    reason TEXT,
    redirected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(new_id) REFERENCES bodies(id) ON DELETE CASCADE
);

-- FTS5 external content
CREATE VIRTUAL TABLE IF NOT EXISTS bodies_fts USING fts5(
    id,
    name,
    designations_json,
    aliases_json,
    classification,
    system,
    discoverer,
    content='bodies',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS bodies_ai AFTER INSERT ON bodies BEGIN
    INSERT INTO bodies_fts(rowid, id, name, designations_json, aliases_json, classification, system, discoverer)
    VALUES (new.rowid, new.id, new.name, new.designations_json, new.aliases_json, new.classification, new.system, new.discoverer);
END;

CREATE TRIGGER IF NOT EXISTS bodies_ad AFTER DELETE ON bodies BEGIN
    INSERT INTO bodies_fts(bodies_fts, rowid, id, name, designations_json, aliases_json, classification, system, discoverer)
    VALUES ('delete', old.rowid, old.id, old.name, old.designations_json, old.aliases_json, old.classification, old.system, old.discoverer);
END;

CREATE TRIGGER IF NOT EXISTS bodies_au AFTER UPDATE ON bodies BEGIN
    INSERT INTO bodies_fts(bodies_fts, rowid, id, name, designations_json, aliases_json, classification, system, discoverer)
    VALUES ('delete', old.rowid, old.id, old.name, old.designations_json, old.aliases_json, old.classification, old.system, old.discoverer);
    INSERT INTO bodies_fts(rowid, id, name, designations_json, aliases_json, classification, system, discoverer)
    VALUES (new.rowid, new.id, new.name, new.designations_json, new.aliases_json, new.classification, new.system, new.discoverer);
END;

-- Note: updated_at managed by Python (explicit snapshots) — avoiding recursive trigger

CREATE INDEX IF NOT EXISTS idx_bodies_classification ON bodies(classification);
CREATE INDEX IF NOT EXISTS idx_bodies_parent_id ON bodies(parent_id);
CREATE INDEX IF NOT EXISTS idx_bodies_system ON bodies(system);
CREATE INDEX IF NOT EXISTS idx_bodies_system_id ON bodies(system_id);
CREATE INDEX IF NOT EXISTS idx_bodies_semi_major_axis_au ON bodies(semi_major_axis_au);
CREATE INDEX IF NOT EXISTS idx_bodies_radius_km ON bodies(radius_km);
CREATE INDEX IF NOT EXISTS idx_bodies_discovery_year ON bodies(discovery_year);
CREATE INDEX IF NOT EXISTS idx_bodies_confidence ON bodies(confidence_score);
CREATE INDEX IF NOT EXISTS idx_bodies_superseded ON bodies(superseded_by);
CREATE INDEX IF NOT EXISTS idx_systems_distance ON systems(distance_pc);
