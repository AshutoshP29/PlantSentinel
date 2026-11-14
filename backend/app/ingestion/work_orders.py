"""F1: load CMMS exports (CSV / XLSX) of work orders and the equipment register into SQLite.

Free text is stored as-is (description_clean / failure modes are set later by clustering).
`redact` is the hook for the Guard's PII redaction (Presidio) before anything is stored.
"""

import io
import sqlite3
from collections.abc import Callable

import pandas as pd

Redactor = Callable[[str], str]

# Accept common CMMS header variants (compared lowercase, spaces/dots -> underscore).
WO_ALIASES = {
    "id": ["id", "wo_id", "work_order", "work_order_id", "wo_no", "order", "notification"],
    "tag": ["tag", "equipment", "equipment_tag", "asset", "asset_tag", "functional_location"],
    "date": ["date", "wo_date", "reported_on", "created_on", "start_date", "malfunction_start"],
    "description": ["description", "short_text", "problem", "problem_description", "text"],
    "action_taken": ["action_taken", "action", "remarks", "work_done", "long_text"],
    "downtime_hrs": ["downtime_hrs", "downtime", "downtime_hours", "breakdown_duration"],
    "cost_inr": ["cost_inr", "cost", "actual_cost", "total_cost"],
}
WO_REQUIRED = ["id", "tag", "date", "description"]
ASSET_COLUMNS = ["tag", "type", "location", "criticality", "install_date"]


def read_table(content: bytes, filename: str) -> pd.DataFrame:
    """Parse an uploaded CSV or Excel file (first sheet)."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(io.BytesIO(content), engine="openpyxl")
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    raise ValueError(f"Unsupported file type: {filename} (use .csv or .xlsx)")


def _key(col: str) -> str:
    return str(col).strip().lower().replace(" ", "_").replace(".", "").replace("-", "_")


def normalise_work_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Map header variants to schema names and clean types (ValueError if columns missing)."""
    by_key = {_key(c): c for c in df.columns}
    mapping = {}
    for target, aliases in WO_ALIASES.items():
        found = next((by_key[a] for a in aliases if a in by_key), None)
        if found is not None:
            mapping[found] = target
    out = df.rename(columns=mapping)
    missing = [c for c in WO_REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {missing}. Found: {list(df.columns)}")
    for c in WO_ALIASES:
        if c not in out.columns:
            out[c] = None
    out = out[list(WO_ALIASES)].copy()
    out["id"] = out["id"].astype(str).str.strip()
    out["tag"] = out["tag"].astype(str).str.strip().str.upper()
    out["date"] = pd.to_datetime(out["date"], errors="coerce", dayfirst=False).dt.date
    for c in ("downtime_hrs", "cost_inr"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ("description", "action_taken"):
        out[c] = out[c].where(out[c].notna(), None)
    return out


def ingest_work_orders(
    conn: sqlite3.Connection, df: pd.DataFrame, redact: Redactor | None = None
) -> dict:
    """Insert work orders; existing ids are skipped (re-uploading the same export is safe)."""
    wo = normalise_work_orders(df)
    bad_date = wo["date"].isna()
    errors = [f"{i}: unreadable date" for i in wo.loc[bad_date, "id"]][:20]
    wo = wo[~bad_date & (wo["id"] != "") & (wo["id"] != "nan")]

    known = {r[0] for r in conn.execute("SELECT tag FROM assets")}
    new_tags = sorted(set(wo["tag"]) - known)
    inserted = 0
    with conn:
        conn.executemany(
            "INSERT INTO assets(tag, type, location, criticality) VALUES (?, 'unknown', NULL, 'C')",
            [(t,) for t in new_tags],
        )
        for r in wo.itertuples(index=False):
            desc, action = r.description, r.action_taken
            if redact:
                desc = redact(desc) if desc else desc
                action = redact(action) if action else action
            cur = conn.execute(
                """INSERT OR IGNORE INTO work_orders
                   (id, tag, date, description, action_taken, downtime_hrs, cost_inr)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.id,
                    r.tag,
                    r.date.isoformat(),
                    desc,
                    action,
                    None if pd.isna(r.downtime_hrs) else float(r.downtime_hrs),
                    None if pd.isna(r.cost_inr) else float(r.cost_inr),
                ),
            )
            inserted += cur.rowcount
    return {
        "rows": len(df),
        "inserted": inserted,
        "duplicates_skipped": len(wo) - inserted,
        "rejected": int(bad_date.sum()),
        "errors": errors,
        "new_assets": new_tags,
    }


def ingest_assets(conn: sqlite3.Connection, df: pd.DataFrame) -> dict:
    """Upsert the equipment register (keeps work orders attached to existing tags)."""
    a = df.rename(columns={c: _key(c) for c in df.columns})
    missing = [c for c in ASSET_COLUMNS if c not in a.columns]
    if missing:
        raise ValueError(f"Missing asset column(s): {missing}")
    a = a[ASSET_COLUMNS].copy()
    a["tag"] = a["tag"].astype(str).str.strip().str.upper()
    a["criticality"] = a["criticality"].astype(str).str.strip().str.upper()
    bad = ~a["criticality"].isin(["A", "B", "C"])
    with conn:
        conn.executemany(
            """INSERT INTO assets(tag, type, location, criticality, install_date)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tag) DO UPDATE SET type = excluded.type,
                 location = excluded.location, criticality = excluded.criticality,
                 install_date = excluded.install_date""",
            [tuple(None if pd.isna(v) else v for v in r) for r in a[~bad].itertuples(index=False)],
        )
    return {"rows": len(a), "upserted": int((~bad).sum()), "rejected": a.loc[bad, "tag"].tolist()}
