import pytest

from app.core.auth import AuthError, NotRegistered, load_user, resolve_email
from app.core.config import Settings


def test_scope_sv_only_own_team(backend, users):
    rows = backend.list_agents(users["sv"].scope)
    assert rows and {a["team"] for a in rows} == {"R1-A"}


def test_scope_manager_and_admin_all(backend, users):
    assert len(backend.list_agents(users["manager"].scope)) == 30
    assert len(backend.list_agents(users["admin"].scope)) == 30


def test_viewer_limited_teams_and_readonly(backend, users):
    v = users["viewer"]
    assert {a["team"] for a in backend.list_agents(v.scope)} == {"R1-A", "R1-B"}
    assert not v.can_write
    assert not v.can_view_sensitive("R1-A")


def test_sensitive_rules(users):
    assert users["sv"].can_view_sensitive("R1-A")
    assert not users["sv"].can_view_sensitive("R2-A")
    assert users["manager"].can_view_sensitive("R2-A")
    assert not users["admin"].can_view_sensitive("R1-A")   # 관리자는 설정·권한 담당


def test_get_agent_outside_scope_is_none(backend, users):
    other = backend.list_agents(users["manager"].scope, team="R2-A")[0]["agent_id"]
    assert backend.get_agent(users["sv"].scope, other) is None


def test_resolve_email_local_cookie():
    s = Settings(env="local", dev_user="sv.kim@example.com")
    assert resolve_email({}, {"dev_user": "Manager@Example.com"}, s) == "manager@example.com"
    assert resolve_email({}, {}, s) == "sv.kim@example.com"


def test_resolve_email_prod_iap_header():
    s = Settings(env="prod")
    h = {"X-Goog-Authenticated-User-Email": "accounts.google.com:SV.Kim@example.com"}
    assert resolve_email(h, {}, s) == "sv.kim@example.com"
    with pytest.raises(AuthError):
        resolve_email({}, {"dev_user": "x@example.com"}, s)   # prod 에서는 쿠키로 로그인 불가


def test_unregistered_user(backend):
    with pytest.raises(NotRegistered):
        load_user("nobody@example.com", backend)


def test_prod_allowed_domain_only():
    s = Settings(env="prod", allowed_domains=("ubase.co.kr",))
    ok = {"X-Goog-Authenticated-User-Email": "accounts.google.com:sv.kim@ubase.co.kr"}
    assert resolve_email(ok, {}, s) == "sv.kim@ubase.co.kr"
    with pytest.raises(AuthError):
        resolve_email({"X-Goog-Authenticated-User-Email": "accounts.google.com:x@gmail.com"}, {}, s)


def test_dotenv_inline_comment_and_bad_env(tmp_path, monkeypatch):
    from app.core import config
    assert config._clean_value("local      # local | prod") == "local"
    assert config._clean_value('"a#b"  # 설명') == "a#b"
    assert config._clean_value("sv.kim@example.com") == "sv.kim@example.com"
    monkeypatch.setenv("ENV", "local   # 설명")
    config.get_settings.cache_clear()
    assert config.get_settings().is_local
    monkeypatch.setenv("ENV", "staging")
    config.get_settings.cache_clear()
    with pytest.raises(ValueError):
        config.get_settings()
    config.get_settings.cache_clear()
