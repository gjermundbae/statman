from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from statman import registry


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Peker STATMAN_ROOT mot en tom midlertidig prosjektrot."""
    monkeypatch.setenv("STATMAN_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def isolated_registry() -> Iterator[type[registry.Model] | None]:
    """Tomt modellregister, uten at de ekte modellene lastes inn."""
    saved = registry.registry()
    saved_flag = registry._discovered
    registry._REGISTRY.clear()
    registry._discovered = True  # blokkerer discover()
    try:
        yield None
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)
        registry._discovered = saved_flag


@pytest.fixture
def con():
    from statman import io

    connection = io.connect()
    try:
        yield connection
    finally:
        connection.close()
