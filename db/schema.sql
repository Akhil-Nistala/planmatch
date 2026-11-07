-- PlanMatch reference database schema (SQLite).
-- Built by `python -m db.build_db` from the CSV seeds in db/seed/. Never edit the .sqlite by hand.

PRAGMA foreign_keys = ON;

-- One row per material TYPE (entry_level='type') or PRODUCT (entry_level='product').
-- For types/products with contains_asbestos in ('yes','varies'), production_start/end_year is the
-- period during which ASBESTOS-CONTAINING versions were manufactured (MLIT 製造時期), not the
-- period the material type existed. NULL = unknown (e.g. MLIT lists "～1980" -> start NULL).
CREATE TABLE materials (
    material_id            TEXT PRIMARY KEY,
    entry_level            TEXT NOT NULL CHECK (entry_level IN ('type', 'product')),
    parent_type_id         TEXT REFERENCES materials(material_id),   -- products point at their type
    material_type_jp       TEXT NOT NULL,
    material_type_en       TEXT NOT NULL,
    product_name           TEXT,
    manufacturer           TEXT,
    asbestos_type          TEXT,          -- e.g. 'chrysotile', 'amosite;chrysotile', NULL = unknown
    production_start_year  INTEGER,
    production_end_year    INTEGER,
    contains_asbestos      TEXT NOT NULL CHECK (contains_asbestos IN ('yes', 'no', 'varies')),
    dust_level             INTEGER CHECK (dust_level IN (1, 2, 3)),  -- 発じん性レベル (MLIT/MHLW)
    usage_parts            TEXT,          -- ';'-separated canonical parts: floor;baseboard;wall;ceiling;exterior;roof;...
    verification           TEXT NOT NULL CHECK (verification IN ('verified', 'assumption', 'placeholder')),
    source_url             TEXT,
    source_note            TEXT,
    CHECK (production_start_year IS NULL OR production_end_year IS NULL
           OR production_start_year <= production_end_year),
    CHECK (entry_level = 'type' OR parent_type_id IS NOT NULL)
);

-- Surface forms that map to a material entry.
CREATE TABLE aliases (
    alias        TEXT NOT NULL,
    material_id  TEXT NOT NULL REFERENCES materials(material_id),
    kind         TEXT NOT NULL CHECK (kind IN
                   ('canonical', 'kana_variant', 'kanji_variant', 'abbreviation',
                    'old_name', 'english', 'shorthand', 'mlit_name')),
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'assumption', 'placeholder')),
    note         TEXT,
    PRIMARY KEY (alias, material_id)
);

CREATE INDEX idx_aliases_alias ON aliases(alias);

-- Provenance of the build itself.
CREATE TABLE build_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
