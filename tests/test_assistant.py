"""AI 질문 — 실제 API 없이 가짜 응답으로 해석·권한·대화 규칙·감사 로그·HTML 안전성을 확인."""
import json

import pytest

from app.core.ai.data_agent import DataAgent, DataAgentError, conversation_prefix, parse
from app.core.ai.render import answer_html, md_to_html
from app.core.errors import InvalidInput, PermissionDenied
from app.modules.assistant.services import ask as ask_svc

SCREEN = {"roles": ["manager", "admin"], "max_question": 1000}

CHAT_RESP = [
    {"systemMessage": {"text": {"parts": ["생각 중"], "textType": "THOUGHT"}}},
    {"systemMessage": {"text": {"parts": ["지난주 **R1** NPS 입니다."]}}},
    {"systemMessage": {"data": {"generatedSql": "SELECT ls, nps FROM t"}}},
    {"systemMessage": {"data": {"result": {"schema": {"fields": [{"name": "ls"}, {"name": "nps"}]},
                                           "data": [{"ls": "R1", "nps": 79.9}, {"ls": "R2", "nps": 68.9}]}}}},
    {"systemMessage": {"text": {"parts": ["| 구분 | 값 |\n|---|---|\n| R1 | 79.9 |\n\n시트 복붙용:\n```\nR1\t79.9\n```"]}}},
]


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self.text = status, body if isinstance(body, str) else json.dumps(body)


class FakeSession:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "body": json.loads(data) if data else None, "headers": headers})
        status, body = self.script.pop(0)
        return FakeResp(status, body)


def _agent(script):
    s = FakeSession(script)
    return DataAgent("v11-2026", "global", "agent_x", session=s), s


def test_parse_order_and_cleanup():
    ans = parse(CHAT_RESP)
    kinds = [s["type"] for s in ans.segments]
    assert kinds == ["text", "table", "text"]                 # 추론 제외, 응답 순서 유지
    assert ans.sqls == ["SELECT ls, nps FROM t"]
    assert "복붙" not in ans.segments[2]["text"] and "\t" not in ans.segments[2]["text"]
    assert "| R1 | 79.9 |" in ans.segments[2]["text"]           # 마크다운 표는 남김


def test_html_is_escaped():
    h = md_to_html('<script>alert(1)</script> **굵게** <img src=x onerror=1>\n| a | <b>x</b> |\n|---|---|\n| 1 | 2 |')
    assert "<script>" not in h and "<img" not in h and "&lt;script&gt;" in h
    assert "<b>굵게</b>" in h and "<table" in h and "&lt;b&gt;x&lt;/b&gt;" in h
    seg_html = answer_html(parse([{"systemMessage": {"data": {"result": {"data": [{"c": "<i>z</i>"}]}}}}]))
    assert "<i>z</i>" not in seg_html and "&lt;i&gt;z&lt;/i&gt;" in seg_html


def test_ask_creates_conversation_with_user_prefix_and_quota_header():
    agent, s = _agent([(200, {"name": "projects/v11-2026/locations/global/conversations/c1"}), (200, CHAT_RESP)])
    ans = agent.ask("지난주 NPS", prefix=conversation_prefix("a@ubase.co.kr"))
    assert ans.mode == "conversation" and ans.conversation.endswith("/c1")
    assert "conversationId=" + conversation_prefix("a@ubase.co.kr") in s.calls[0]["url"]
    assert s.calls[1]["body"]["conversationReference"]["dataAgentContext"]["dataAgent"].endswith("dataAgents/agent_x")
    assert s.calls[1]["headers"]["X-Goog-User-Project"] == "v11-2026"


def test_other_users_conversation_is_ignored():
    agent, s = _agent([(200, {"name": "n/new"}), (200, CHAT_RESP)])
    other = "projects/v11-2026/locations/global/conversations/" + conversation_prefix("b@ubase.co.kr") + "zzz"
    agent.ask("q", prefix=conversation_prefix("a@ubase.co.kr"), conversation=other)
    assert "/conversations?conversationId=" in s.calls[0]["url"]     # 새 대화를 만듦
    assert s.calls[1]["body"]["conversationReference"]["conversation"] == "n/new"


def test_expired_conversation_retries_then_single_fallback():
    p = conversation_prefix("a@ubase.co.kr")
    mine = "projects/v11-2026/locations/global/conversations/" + p + "old"
    agent, s = _agent([(404, "gone"), (200, {"name": "n/fresh"}), (200, CHAT_RESP)])
    ans = agent.ask("q", prefix=p, conversation=mine)
    assert ans.conversation == "n/fresh"
    agent, s = _agent([(500, "boom"), (200, CHAT_RESP)])          # 대화 생성 실패 → 한 번 묻기
    ans = agent.ask("q", prefix=p)
    assert ans.mode == "single" and "dataAgentContext" in s.calls[1]["body"] and ans.notes


def test_permission_error_is_not_hidden():
    agent, _ = _agent([(200, {"name": "n/c"}), (403, "PERMISSION_DENIED")])
    with pytest.raises(DataAgentError) as e:
        agent.ask("q", prefix="p-")
    assert e.value.status == 403 and "권한" in str(e.value)


def test_service_rules_and_audit(backend, users):
    agent, _ = _agent([(200, {"name": "n/c"}), (200, CHAT_RESP)])
    with pytest.raises(PermissionDenied):
        ask_svc.ask(backend, agent, users["sv"], SCREEN, "q")
    with pytest.raises(InvalidInput):
        ask_svc.ask(backend, agent, users["manager"], SCREEN, "  ")
    with pytest.raises(InvalidInput):
        ask_svc.ask(backend, agent, users["manager"], SCREEN, "x" * 1001)
    ans = ask_svc.ask(backend, agent, users["manager"], SCREEN, "지난주 NPS")
    assert ans.sqls
    last = json.loads((backend.runtime / "audit_log.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last["action"] == "ai_ask" and last["detail"]["question"] == "지난주 NPS" and last["detail"]["ok"]


def test_not_configured(backend, users):
    with pytest.raises(DataAgentError) as e:
        ask_svc.ask(backend, None, users["manager"], SCREEN, "q")
    assert e.value.status == 503


def test_page_and_menu_by_role(backend, users):
    from app.core import templating
    from app.core.modules import discover
    from app.modules.assistant.views import page_context
    mods = {m.name: m for m in discover(with_routers=False)}
    m = mods["assistant"]
    html = templating.render("assistant/ask.html", page_context(users["manager"], m.screen("ask")),
                             user=users["manager"], module=m, active="ask", with_routers=False)
    assert "AI 질문" in html and 'class="ai-chat"' in html and 'class="ai-dock"' not in html   # 큰 화면엔 패널 없음
    for role in ("admin", "manager", "sv", "viewer"):              # 웹 접속자 누구나
        assert page_context(users[role], m.screen("ask")) and m.menu_for(role)
    with pytest.raises(PermissionDenied):                          # roles 를 줄이면 막힘
        page_context(users["sv"], {**m.screen("ask"), "roles": ["manager"]})


def test_right_dock_on_other_pages_by_role(backend, users, screens):
    from app.core import templating
    from app.core.modules import discover
    from app.modules.agent360 import views
    m = next(x for x in discover(with_routers=False) if x.name == "agent360")
    for role, expect in (("manager", True), ("admin", True), ("sv", True), ("viewer", True)):
        u = users[role]
        html = templating.render("agent360/agents.html", views.agents(backend, u, screens), user=u, module=m,
                                 active="agents", with_routers=False)
        assert ('class="ai-dock"' in html) is expect, role
        assert ("with-ai" in html) is expect, role
