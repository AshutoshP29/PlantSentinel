"""Loader for the AI4I 2020 Predictive Maintenance dataset (UCI)."""

from pathlib import Path

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
TYPE_CODES = {"L": 0, "M": 1, "H": 2}
FEATURES = [*NUMERIC_FEATURES, "type_code"]
TARGET = "failure"
# Failure sub-type flags: they leak the target, never use them as features.
LEAKY = ["twf", "hdf", "pwf", "osf", "rnf"]

FEATURE_LABELS = {
    "air_temp_k": "Air temperature",
    "process_temp_k": "Process temperature",
    "rpm": "Rotational speed",
    "torque_nm": "Torque",
    "tool_wear_min": "Tool / component wear",
    "type_code": "Product quality grade",
}


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
    df["type_code"] = df["type"].map(TYPE_CODES).astype(int)
    df[TARGET] = df[TARGET].astype(int)
    return df
