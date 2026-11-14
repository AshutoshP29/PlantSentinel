"""Loader for the AI4I 2020 Predictive Maintenance dataset (UCI)."""

from pathlib import Path

import numpy as np
import pandas as pd

from app.config import get_settings

RENAME = {
    "UDI": "udi",
    "Product ID": "product_id",
    "Type": "type",
    "Air temperature [K]": "air_temp_k",
    "Process temperature [K]": "process_temp_k",
    "Rotational speed [rpm]": "rpm",
    "Torque [Nm]": "torque_nm",
    "Tool wear [min]": "tool_wear_min",
    "Machine failure": "failure",
    "TWF": "twf",
    "HDF": "hdf",
    "PWF": "pwf",
    "OSF": "osf",
    "RNF": "rnf",
}

NUMERIC_FEATURES = ["air_temp_k", "process_temp_k", "rpm", "torque_nm", "tool_wear_min"]
# Physically meaningful combinations of the raw sensors (heat dissipation, power, overstrain).
ENGINEERED_FEATURES = ["temp_diff_k", "power_kw", "strain_nm_min"]
TYPE_CODES = {"L": 0, "M": 1, "H": 2}
FEATURES = [*NUMERIC_FEATURES, *ENGINEERED_FEATURES, "type_code"]
TARGET = "failure"
# Failure sub-type flags: they leak the target, never use them as features.
LEAKY = ["twf", "hdf", "pwf", "osf", "rnf"]

FEATURE_LABELS = {
    "air_temp_k": "Air temperature",
    "process_temp_k": "Process temperature",
    "rpm": "Rotational speed",
    "torque_nm": "Torque",
    "tool_wear_min": "Component wear time",
    "temp_diff_k": "Heat-dissipation margin (process - air temp)",
    "power_kw": "Mechanical power",
    "strain_nm_min": "Overstrain (torque x wear)",
    "type_code": "Duty class",
}


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add engineered features and `type_code` from raw columns (works on 1-row frames too)."""
    out = df.copy()
    out["temp_diff_k"] = out["process_temp_k"] - out["air_temp_k"]
    out["power_kw"] = out["torque_nm"] * out["rpm"] * 2 * np.pi / 60 / 1000
    out["strain_nm_min"] = out["torque_nm"] * out["tool_wear_min"]
    if "type_code" not in out:
        out["type_code"] = out["type"].map(TYPE_CODES).astype(int)
    return out


def default_path() -> Path:
    return get_settings().data_dir / "raw" / "ai4i2020.csv"


def load_ai4i(path: Path | None = None) -> pd.DataFrame:
    """Load AI4I 2020 with snake_case columns and an integer `type_code`.

    Raises ValueError if expected columns are missing or values are null.
    """
    df = pd.read_csv(path or default_path(), encoding="utf-8-sig")
    missing = set(RENAME) - set(df.columns)
    if missing:
        raise ValueError(f"AI4I file is missing columns: {sorted(missing)}")
    df = df.rename(columns=RENAME)[list(RENAME.values())]
    if df.isna().any().any():
        raise ValueError("AI4I file contains null values")
    unknown = set(df["type"]) - set(TYPE_CODES)
    if unknown:
        raise ValueError(f"Unknown product types: {sorted(unknown)}")
    df[TARGET] = df[TARGET].astype(int)
    return add_features(df)
