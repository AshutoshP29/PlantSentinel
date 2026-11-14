"""SQLite connection helpers and schema initialisation."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  tag TEXT PRIMARY KEY, type TEXT, location TEXT,
  criticality TEXT CHECK(criticality IN ('A','B','C')), install_date TEXT);

CREATE TABLE IF NOT EXISTS failure_modes(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT);

CREATE TABLE IF NOT EXISTS work_orders(
  id TEXT PRIMARY KEY, tag TEXT REFERENCES assets(tag), date TEXT,
  description TEXT, description_clean TEXT, action_taken TEXT,
  downtime_hrs REAL, cost_inr REAL,
  failure_mode_id INTEGER REFERENCES failure_modes(id));

CREATE TABLE IF NOT EXISTS inspections(
  id TEXT PRIMARY KEY, tag TEXT REFERENCES assets(tag), date TEXT,
  file_path TEXT, raw_text TEXT, extracted_json TEXT);

CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, role TEXT,
  action TEXT, tool TEXT, input TEXT, output TEXT,
  status TEXT CHECK(status IN ('allowed','blocked','error')));
"""

TABLES = ("assets", "failure_modes", "work_orders", "inspections", "audit_log")


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()
