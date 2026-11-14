from collections.abc import Iterator
from pathlib import Path

import pytest

from app import config


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point every writable path at a temp dir so tests never touch real data/caches."""
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
