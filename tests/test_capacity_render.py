"""Capacity 화면 — 역할별 렌더·권한, BigQuery 매개변수."""
import re
import sys
import types

import pytest

from app.core import templating
from app.core.errors import PermissionDenied
from app.core.modules import discover
from app.modules.capacity import views
from app.modules.capacity.data import get_store


@pytest.fixture()
def cap():
    return next(m for m in discover(with_routers=False) if m.name == "capacity")


@pytest.fixture()
def cap_users(backend, users):
    from app.core.auth import load_user
    return {**users, "wfm": load_user("wfm@example.com", backend)}


def _r(tpl, ctx, user, mod, active=""):
    return templating.render(tpl, ctx, user=user, module=mod, active=active, with_routers=False)


@pytest.mark.parametrize("role", ["admin", "manager", "wfm", "viewer"])
def test_home_renders(backend, cap_users, cap, role):
    u = cap_users[role]
    ctx = views.home(backend, get_store(), u, cap.screens)
    assert ctx["week"] == "2026-11-21" and ctx["now"]["required"] > 0
    html = _r("capacity/home.html", ctx, u, cap, "home")
    for word in ("FTE 대시보드", "주별 FTE 갭", "계산 가정", "<svg", "bar-"):
        assert word in html


def test_sv_has_no_capacity(backend, cap_users, cap):
    with pytest.raises(PermissionDenied):
        views.home(backend, get_store(), cap_users["sv"], cap.screens)
    assert cap.menu_for("sv") == []


def test_menu_by_role(cap):
    ids = lambda r: [m["id"] for m in cap.menu_for(r)]  # noqa: E731
    assert "input" in ids("wfm") and "input" not in ids("manager") and "simulator" not in ids("viewer")


@pytest.mark.parametrize("sid", ["absence", "cohorts", "simulator", "input", "reports"])
def test_placeholders(cap_users, cap, sid):
    u = cap_users["wfm"]
    assert "준비 중" in _r("capacity/placeholder.html", views.placeholder(u, cap.screens, sid), u, cap, sid)


def test_viewer_blocked_from_input(cap_users, cap):
    with pytest.raises(PermissionDenied):
        views.placeholder(cap_users["viewer"], cap.screens, "input")


def test_bigquery_params_bound(monkeypatch):
    calls = []

    class P:
        def __init__(self, name, typ, value):
            self.name = name

    class Cfg:
        def __init__(self, query_parameters=()):
            self.p = list(query_parameters)

    class Client:
        def __init__(self, project=None, **kw):
            self.project = project

        def query(self, sql, job_config=None, location=None):
            calls.append((sql, {p.name for p in job_config.p}))
            return types.SimpleNamespace(result=lambda: [])

    fake = types.ModuleType("google.cloud.bigquery")
    fake.ScalarQueryParameter, fake.QueryJobConfig, fake.Client = P, Cfg, Client
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake
    google = types.ModuleType("google")
    google.cloud = cloud
    for k, v in {"google": google, "google.cloud": cloud, "google.cloud.bigquery": fake}.items():
        monkeypatch.setitem(sys.modules, k, v)
    from app.modules.capacity.data.bigquery import CapacityBigQuery
    b = CapacityBigQuery("v12-2027", "asia-northeast3", "capacity", 0)
    b.forecast("2026-10-01", "2026-12-31"); b.headcount("2026-10-01", "2026-12-31"); b.assumptions()
    assert len(calls) == 3
    for sql, bound in calls:
        assert set(re.findall(r"@(\w+)", sql)) <= bound
        assert "`v12-2027.capacity`" in sql
