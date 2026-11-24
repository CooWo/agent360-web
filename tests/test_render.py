"""화면 렌더링 — 웹 서버 없이 views + 템플릿으로 모든 화면이 오류 없이 나오는지."""
import pytest

from app.core import templating
from app.core.errors import NotFound, PermissionDenied
from app.core.modules import discover
from app.modules.agent360 import views


@pytest.fixture()
def mod():
    return next(m for m in discover(with_routers=False) if m.name == "agent360")


def _r(tpl, ctx, user, mod, active=""):
    return templating.render(tpl, ctx, user=user, module=mod, active=active, with_routers=False)


@pytest.mark.parametrize("role", ["sv", "manager", "viewer", "admin"])
def test_home_and_list_render(backend, users, screens, mod, role):
    u = users[role]
    assert "오늘 볼 상담사" in _r("agent360/home.html", views.home(backend, u, screens), u, mod, "home")
    assert "상담사 목록" in _r("agent360/agents.html", views.agents(backend, u, screens), u, mod, "agents")


def test_detail_render_sections_and_lock(backend, users, screens, mod):
    aid = backend.list_agents(users["sv"].scope)[0]["agent_id"]
    html = _r("agent360/agent_detail.html", {**views.agent_detail(backend, users["sv"], screens, aid), "saved": False}, users["sv"], mod)
    for word in ("KPI 추이", "근태", "QA 평가", "코칭 이력", "교육 이력", "인센티브", "<svg"):
        assert word in html
    v = _r("agent360/agent_detail.html", {**views.agent_detail(backend, users["viewer"], screens, aid), "saved": False}, users["viewer"], mod)
    assert "담당 SV와 매니저만" in v


def test_detail_outside_scope(backend, users, screens):
    other = backend.list_agents(users["manager"].scope, team="R2-A")[0]["agent_id"]
    with pytest.raises(NotFound):
        views.agent_detail(backend, users["sv"], screens, other)


def test_menu_by_role(backend, users, screens, mod):
    html = _r("agent360/home.html", views.home(backend, users["viewer"], screens), users["viewer"], mod, "home")
    assert "/agent360/coaching" not in html and "/agent360/admin" not in html
    html = _r("agent360/home.html", views.home(backend, users["admin"], screens), users["admin"], mod, "home")
    assert "/agent360/admin" in html


def test_coaching_and_admin_permissions(backend, users, screens):
    with pytest.raises(PermissionDenied):
        views.coaching(backend, users["viewer"], screens)
    with pytest.raises(PermissionDenied):
        views.admin(backend, users["sv"], screens)
    assert views.admin(backend, users["admin"], screens)["rules"]


def test_screens_json_controls_sections(backend, users, screens, mod):
    import copy
    sc = copy.deepcopy(screens)
    sc["screens"]["agent_detail"]["sections"] = ["summary", "signals"]
    aid = backend.list_agents(users["sv"].scope)[0]["agent_id"]
    html = _r("agent360/agent_detail.html", {**views.agent_detail(backend, users["sv"], sc, aid), "saved": False}, users["sv"], mod)
    assert "오늘 신호" in html and "교육 이력" not in html


def test_static_urls_have_version():
    from app.core.templating import _static
    assert "/css/app.css?v=" in _static("css/app.css") and not _static("css/app.css").endswith("?v=0")
