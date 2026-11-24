"""테스트 공통: 샘플 데이터 사본으로 돌려 원본·runtime 을 건드리지 않는다."""
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    dst = tmp_path / "sample_data"
    shutil.copytree(ROOT / "sample_data", dst, ignore=shutil.ignore_patterns("runtime", "*.py"))
    monkeypatch.setenv("SAMPLE_DIR", str(dst))
    monkeypatch.setenv("DATA_BACKEND", "sample")
    monkeypatch.setenv("ENV", "local")
    from app.core.config import get_settings
    from app.core.data import get_backend
    get_settings.cache_clear()
    get_backend.cache_clear()
    yield get_backend()
    get_settings.cache_clear()
    get_backend.cache_clear()


@pytest.fixture()
def screens():
    from app.core.modules import discover
    return next(m for m in discover(with_routers=False) if m.name == "agent360").screens


@pytest.fixture()
def users(backend):
    from app.core.auth import load_user
    return {k: load_user(e, backend) for k, e in {
        "sv": "sv.kim@example.com", "sv_b": "sv.lee@example.com", "manager": "manager@example.com",
        "viewer": "viewer@example.com", "admin": "admin@example.com"}.items()}


os.environ.setdefault("ENV", "local")
