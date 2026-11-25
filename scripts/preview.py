"""웹 서버 없이 화면을 HTML 파일로 뽑아 보는 미리보기 (디자인 확인·리뷰용).

python scripts/preview.py            → preview/<역할>_<화면>.html
웹 서버(FastAPI)와 같은 views + 템플릿을 쓰므로 실제 화면과 같다. (버튼 동작은 서버가 있어야 함)
샘플 데이터 사본으로 돌려 원본 runtime 기록은 건드리지 않는다.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="a360_preview_"))
shutil.copytree(ROOT / "sample_data", tmp / "sample_data", ignore=shutil.ignore_patterns("runtime", "*.py"))
os.environ.update(SAMPLE_DIR=str(tmp / "sample_data"), DATA_BACKEND="sample", ENV="local")

from app.core import templating  # noqa: E402
from app.core.auth import load_user  # noqa: E402
from app.core.data import get_backend  # noqa: E402
from app.core.errors import NotFound, PermissionDenied  # noqa: E402
from app.core.modules import discover  # noqa: E402
from app.modules.agent360 import views  # noqa: E402
from app.modules.capacity import views as cap_views  # noqa: E402
from app.modules.capacity.data import get_store  # noqa: E402
from app.modules.capacity.wiring import change_service  # noqa: E402
from app.modules.roster import views as roster_views  # noqa: E402
from app.modules.roster.data import get_store as roster_store  # noqa: E402
from app.modules.roster.wiring import change_service as roster_changes  # noqa: E402

OUT = ROOT / "preview"
OUT.mkdir(exist_ok=True)
templating.STATIC_PREFIX["value"] = os.path.relpath(ROOT / "app" / "static", OUT).replace(os.sep, "/")


def main():
    b = get_backend()
    mod = next(m for m in discover(with_routers=False) if m.name == "agent360")
    sc = mod.screens
    users = ["sv.kim@example.com", "manager@example.com", "viewer@example.com", "admin@example.com"]
    made = []
    for email in users:
        u = load_user(email, b)
        top = views.home(b, u, sc)["ranked"]
        first = top[0]["agent"]["agent_id"] if top else b.list_agents(u.scope)[0]["agent_id"]
        pages = {
            "home": ("agent360/home.html", lambda: views.home(b, u, sc), "home"),
            "agents": ("agent360/agents.html", lambda: views.agents(b, u, sc), "agents"),
            "detail": ("agent360/agent_detail.html", lambda: {**views.agent_detail(b, u, sc, first), "saved": False}, "agents"),
            "coaching": ("agent360/coaching.html", lambda: views.coaching(b, u, sc, agent_id=first), "coaching"),
            "admin": ("agent360/admin.html", lambda: views.admin(b, u, sc), "admin"),
        }
        for name, (tpl, ctx, active) in pages.items():
            try:
                html = templating.render(tpl, ctx(), user=u, module=mod, active=active,
                                         users_for_switch=b.list_users(), with_routers=False)
            except (PermissionDenied, NotFound) as e:
                html = templating.render("errors/error.html", {"status": 403, "message": str(e)}, user=u,
                                         module=mod, with_routers=False)
            p = OUT / f"{u.role}_{name}.html"
            p.write_text(html, encoding="utf-8")
            made.append(p.name)
    cap = next(m for m in discover(with_routers=False) if m.name == "capacity")
    for email in ["wfm@example.com", "manager@example.com", "viewer@example.com"]:
        u = load_user(email, b)
        pages = {"capacity_home": ("capacity/home.html", lambda: cap_views.home(b, get_store(), u, cap.screens), "home"),
                 "capacity_input": ("capacity/input.html", lambda: {**cap_views.input_page(u, cap.screens, change_service(), get_store()),
                                                             "preview": None, "errors": {}}, "input")}
        for name, (tpl, ctx, active) in pages.items():
            try:
                html = templating.render(tpl, ctx(), user=u, module=cap, active=active,
                                         users_for_switch=b.list_users(), with_routers=False)
            except (PermissionDenied, NotFound) as e:
                html = templating.render("errors/error.html", {"status": 403, "message": str(e)}, user=u,
                                         module=cap, with_routers=False)
            p = OUT / f"{u.role}_{name}.html"
            p.write_text(html, encoding="utf-8")
            made.append(p.name)
    ros = next(m for m in discover(with_routers=False) if m.name == "roster")
    for email in ["wfm@example.com", "viewer@example.com"]:
        u = load_user(email, b)
        pages = {"roster_board": ("roster/board.html", lambda: roster_views.team_board(roster_store(), u, ros.screens), "board"),
                 "roster_workspace": ("roster/workspace.html",
                                      lambda: roster_views.workspace(roster_store(), u, ros.screens, roster_changes()),
                                      "workspace")}
        for name, (tpl, ctx, active) in pages.items():
            try:
                html = templating.render(tpl, ctx(), user=u, module=ros, active=active,
                                         users_for_switch=b.list_users(), with_routers=False)
            except (PermissionDenied, NotFound) as e:
                html = templating.render("errors/error.html", {"status": 403, "message": str(e)}, user=u,
                                         module=ros, with_routers=False)
            p = OUT / f"{u.role}_{name}.html"
            p.write_text(html, encoding="utf-8")
            made.append(p.name)
    print("미리보기:", OUT)
    print("\n".join(made))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
