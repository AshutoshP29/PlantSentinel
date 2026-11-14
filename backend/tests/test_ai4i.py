from pathlib import Path

import pytest

from app.analytics import ai4i

HEADER = (
    "UDI,Product ID,Type,Air temperature [K],Process temperature [K],Rotational speed [rpm],"
    "Torque [Nm],Tool wear [min],Machine failure,TWF,HDF,PWF,OSF,RNF\n"
)
ROWS = (
    "1,M14860,M,298.1,308.6,1551,42.8,0,0,0,0,0,0,0\n"
    "2,L47181,L,298.2,308.7,1408,46.3,3,1,0,1,0,0,0\n"
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "ai4i.csv"
    p.write_text(text, encoding="utf-8-sig")  # real file has a BOM
    return p


def test_load_small_file(tmp_path: Path) -> None:
    df = ai4i.load_ai4i(_write(tmp_path, HEADER + ROWS))
    assert list(df["udi"]) == [1, 2]  # BOM must not corrupt the first column name
    assert list(df["type_code"]) == [1, 0]
    assert list(df[ai4i.TARGET]) == [0, 1]
    assert set(ai4i.FEATURES) <= set(df.columns)
    assert not set(ai4i.LEAKY) & set(ai4i.FEATURES)
    assert set(ai4i.FEATURE_LABELS) == set(ai4i.FEATURES)


def test_missing_column_raises(tmp_path: Path) -> None:
    bad = HEADER.replace(",RNF", "") + "1,M1,M,298,308,1500,40,0,0,0,0,0,0\n"
    with pytest.raises(ValueError, match="missing columns"):
        ai4i.load_ai4i(_write(tmp_path, bad))


def test_nulls_raise(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="null"):
        ai4i.load_ai4i(_write(tmp_path, HEADER + "1,M1,M,,308,1500,40,0,0,0,0,0,0,0\n"))


def test_unknown_type_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown product types"):
        ai4i.load_ai4i(_write(tmp_path, HEADER + "1,X1,X,298,308,1500,40,0,0,0,0,0,0,0\n"))


@pytest.mark.skipif(not ai4i.default_path().exists(), reason="AI4I csv not present")
def test_real_dataset() -> None:
    df = ai4i.load_ai4i()
    assert len(df) == 10_000
    assert df[ai4i.TARGET].sum() == 339
