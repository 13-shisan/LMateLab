# backend/utils/qe_epw_schema.py
# -*- coding: utf-8 -*-

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content_hash TEXT NOT NULL UNIQUE,
  structure TEXT,
  code TEXT NOT NULL,
  calc_type TEXT,

  out_path TEXT,
  workdir TEXT,
  mtime_utc TEXT,
  parsed_at_utc TEXT NOT NULL,

  finished_marker TEXT,

  nat INTEGER,
  ntyp INTEGER,
  nelec REAL,
  nbnd INTEGER,
  ecutwfc_ry REAL,
  ecutrho_ry REAL,
  alat_au REAL,
  cell_volume_au3 REAL,
  efermi_ev REAL,
  total_energy_ev REAL,

  qgrid TEXT,
  nqpoints INTEGER,

  qe_in_path TEXT,
  calc_from_in TEXT,
  prefix TEXT,
  structure_json TEXT,

  epw_in_path TEXT,
  epw_params_json TEXT,

  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS file_refs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  out_path TEXT NOT NULL,
  workdir TEXT NOT NULL,
  mtime_utc TEXT,
  first_seen_utc TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL,
  UNIQUE(run_id, out_path),
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mobility (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  carrier TEXT NOT NULL,
  temp_K REAL NOT NULL,
  fermi_ev REAL,
  density_cm2 REAL,
  mu_x_cm2Vs REAL,
  mu_y_cm2Vs REAL,
  raw_json TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mobility_run_id ON mobility(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_structure ON runs(structure);
CREATE INDEX IF NOT EXISTS idx_file_refs_run_id ON file_refs(run_id);
"""
