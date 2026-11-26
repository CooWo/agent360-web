"""AI 브리핑 — 화면에 이미 계산된 숫자를 글로 묶어 데이터 에이전트(AI BA CHAT)에게 요약을 묻는다.

- 숫자는 이 앱의 계산 결과만 보낸다. AI 에게는 '새 숫자를 만들지 말고, 추가 조회 없이' 요약하라고 한다.
- 상담사·TL 이름은 보내지 않는다: '상담사#1', '팀#1' 로 바꿔 보내고, 답을 받은 뒤 화면에서만 이름으로 되돌린다.
- 같은 사람·같은 화면·같은 기준일·같은 내용이면 서버에서 몇 시간 재사용한다 (매번 묻지 않음 → 비용·대기 줄임).
"""
from __future__ import annotations

import hashlib
import html
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone


CACHE_SECS = 6 * 3600
KST = timezone(timedelta(hours=9))
MAX_PROMPT = 4000
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()

RULES = ("규칙: 숫자는 위에 적힌 값만 그대로 쓰고 새 숫자를 계산하거나 만들지 마세요. 추가 데이터 조회 없이 위 내용만으로 답하세요. "
         "사람·팀은 '상담사#번호', '팀#번호' 표기를 그대로 쓰세요. 한국어 글머리표로 짧게.")


class Alias:
    """이름 → 가명 (상담사#1, 팀#1). 답의 가명을 이름으로 되돌린다."""

    def __init__(self):
        self.maps: dict[str, dict[str, str]] = {"상담사": {}, "팀": {}}

    def __call__(self, kind: str, name: str) -> str:
        m = self.maps[kind]
        if name not in m:
            m[name] = f"{kind}#{len(m) + 1}"
        return m[name]

    def restore(self, text_html: str) -> str:
        back = {tag: name for kind in self.maps for name, tag in self.maps[kind].items()}

        def sub(mo):
            tag = f"{mo.group(1)}#{mo.group(2)}"
            return f"<b>{html.escape(back[tag])}</b>" if tag in back else mo.group(0)
        return re.sub(r"(상담사|팀)\s*#\s*(\d+)", sub, text_html)


def is_suggestions(text: str) -> bool:
    """에이전트가 답 끝에 붙이는 '다음에 물어볼 질문' 묶음 (문장이 모두 '…해 줘.' 로 끝남) → 브리핑에서는 숨김."""
    parts = [x.strip() for x in re.split(r"(?<=[.?!])\s*|\n+", str(text or "")) if x.strip()]
    return bool(parts) and all(re.search(r"(줘|주세요|볼까요|할까요)[.?!]?$", x) for x in parts)


def _n(v, d=1) -> str:
    if v is None:
        return "-"
    return f"{v:,.{d}f}" if isinstance(v, float) else str(v)


def home_prompt(ctx: dict, alias: Alias) -> str:
    teams = ctx.get("teams", {})
    lines = [f"[상담 운영 아침 브리핑 요청] 기준일 {ctx['as_of']}. 담당 상담사 {ctx['total_agents']}명, "
             f"신호가 있는 상담사 {ctx['ranked_total']}명."]
    lines.append("■ 먼저 볼 상담사 (신호 점수 높은 순)")
    for r in ctx["ranked"][:5]:
        a = r["agent"]
        sig = "; ".join(f"{s.get('label') or s.get('rule_id')}: {s.get('evidence', '')}" for s in r["signals"][:3])
        lines.append(f"- {alias('상담사', a['name'])} ({alias('팀', teams.get(a['team'], a['team']))}) 점수 {r['score']} — {sig}")
    if not ctx["ranked"]:
        lines.append("- 오늘 신호 없음")
    gaps = ctx.get("gaps") or []
    lines.append(f"■ 코칭 부족 {len(gaps)}명 (코칭 횟수 < QA 평가 횟수), Rate 낮은 순 상위 5명")
    for g in gaps[:5]:
        lines.append(f"- {alias('상담사', g['name'])} ({alias('팀', g['team'])}) QA 평균 {_n(g.get('qa_avg'))}점, "
                     f"평가 {g['evaluations']} · 코칭 {g['coaching_sessions']} · Rate {_n(g['rate'], 0)}% · 남은 코칭 {g['missing']}")
    fu = ctx.get("followups") or {}
    names = ctx.get("names", {})
    lines.append(f"■ 코칭 후속 확인: 기한 지남 {len(fu.get('overdue', []))}건, "
                 f"{ctx['cfg'].get('followup_days', 3)}일 안 예정 {len(fu.get('soon', []))}건")
    for c in (fu.get("overdue", []) + fu.get("soon", []))[:5]:
        lines.append(f"- {alias('상담사', names.get(c['agent_id'], c['agent_id']))} {c.get('issue_type', '')} 후속 {c.get('follow_up_date', '')}")
    lines.append("요청: 팀장이 오늘 아침 먼저 할 일을 우선순위대로 3~5줄로 브리핑해 주세요. " + RULES)
    return "\n".join(lines)[:MAX_PROMPT]


def agent_prompt(ctx: dict, alias: Alias) -> str:
    a = ctx["agent"]
    who = alias("상담사", a["name"])
    lines = [f"[상담사 요약 요청] 기준일 {ctx['as_of']}. {who} ({alias('팀', ctx['team_label'])}), 상태 {a.get('status', '')}"
             + (f", 입사 {a['hire_date']}" if a.get("hire_date") else "") + (f", 기수 {a['cohort']}" if a.get("cohort") else "")
             + (f", 램프업 주 {', '.join(ctx['ramping_weeks'])}" if ctx.get("ramping_weeks") else "") + "."]
    lines.append("■ KPI 최근 4주 (직전 4주 · 목표, better=좋아지는 방향)")
    for c in ctx["charts"]:
        lines.append(f"- {c['label']}: {_n(c['recent'], c['digits'])}{c['unit']} (직전 {_n(c['prior'], c['digits'])}"
                     + (f", 목표 {_n(c['target'], c['digits'])}" if c.get("target") is not None else "")
                     + f", better={'높을수록' if c['better'] == 'up' else '낮을수록'})")
    att = ctx["attendance"]
    cnt = att.get("count", {})
    lines.append(f"■ 근태 최근 {ctx['cfg'].get('attendance_days', 30)}일: "
                 + ", ".join(f"{k} {cnt.get(k, 0)}" for k in ("결근", "지각", "조퇴", "연차", "휴가", "휴직", "연장근로", "교육")))
    q = ctx.get("qa_upload")
    if q:
        lines.append(f"■ QA·코칭 (올린 파일): QA 평균 {_n(q.get('qa_avg'))}점, 평가 {q.get('evaluations')} · 코칭 "
                     f"{q.get('coaching_sessions')}, 등급 Bad {q.get('grade_bad') or 0} · NI {q.get('grade_ni') or 0} · "
                     f"Good {q.get('grade_good') or 0} · VG {q.get('grade_very_good') or 0}"
                     + (" — 코칭 필요" if q.get("need") else ""))
    elif ctx.get("qa_avg") is not None:
        lines.append(f"■ QA 최근 평균 {_n(ctx['qa_avg'])}점 ({len(ctx.get('qa', []))}건)")
    lines.append("■ 신호: " + ("; ".join(f"{s.get('label') or s.get('rule_id')} {s.get('evidence', '')}" for s in ctx["signals"][:5])
                               or "없음"))
    lines.append(f"■ 코칭 기록 {ctx.get('coaching_count', 0)}건" + (f", 마지막 {ctx['last_coaching']}" if ctx.get("last_coaching") else ""))
    lines.append(f"요청: {who}의 지금 상태를 3~5줄로 요약해 주세요 (잘하는 점 · 걱정되는 점 · 이번 주 코칭 제안). " + RULES)
    return "\n".join(lines)[:MAX_PROMPT]


DETRACTOR_WEEKS = 8


def detractor_facts(rows: list[dict]) -> dict:
    """설문 응답 → 디트랙터 건수·주차별·문의 유형 상위 (숫자는 여기서만 만든다)."""
    from collections import Counter

    from app.modules.agent360.services.kpi import week_end
    det = [r for r in rows if r.get("is_detractor")]
    weekly = Counter(week_end(date.fromisoformat(r["resp_date"])).isoformat() for r in det)
    return {"responses": len(rows), "detractors": len(det),
            "rate": (len(det) / len(rows) * 100) if rows else None,
            "weekly": sorted(weekly.items()), "by_cr": Counter(r.get("cr_parent") or "(없음)" for r in det).most_common(3),
            "comments": [r for r in det if (r.get("comment") or "").strip()]}


def detractor_prompt(facts: dict, as_of: str, weeks: int = DETRACTOR_WEEKS) -> str:
    """디트랙터 코멘트 요약 질문 — 건수는 이미 계산한 값, 코멘트만 AI 가 주제별로 묶는다 (상담사 이름·LDAP 은 안 보냄)."""
    lines = [f"[상담사 디트랙터 코멘트 요약] 기준일 {as_of}, 최근 {weeks}주 고객 설문: 응답 {facts['responses']}건 중 "
             f"디트랙터(NPS 0~6) {facts['detractors']}건.",
             "■ 문의 유형 상위: " + ", ".join(f"{k} {v}건" for k, v in facts["by_cr"]),
             "■ 디트랙터 코멘트 (날짜 · NPS · 문의 유형 · 코멘트)"]
    for r in facts["comments"][:15]:
        lines.append(f"- {r['resp_date']} · {r['nps']} · {r.get('cr_child') or r.get('cr_parent')} · {(r['comment'] or '')[:300]}")
    lines.append("요청: 코멘트를 주제별로 묶어 3~5줄로 요약하고 (상담사 응대 문제인지, 정책·제품 문제인지 구분), "
                 "마지막에 이 상담사 코칭 포인트 1~2줄. 코멘트 원문을 길게 옮기지 말고, 고객 이름·연락처·예약번호 같은 개인정보는 쓰지 마세요. " + RULES)
    return "\n".join(lines)[:MAX_PROMPT]


def brief(backend, agent, user, screen: dict, key: str, prompt: str, alias: Alias, refresh: bool = False) -> dict:
    """요약 받기 (캐시). 반환 {html, secs, cached, asked_at}. 권한·감사 로그는 AI 질문과 같은 규칙."""
    ck = (user.email, key, hashlib.sha1(prompt.encode("utf-8")).hexdigest())
    now = time.time()
    with _lock:
        hit = _cache.get(ck)
    if hit and not refresh and now - hit[0] < CACHE_SECS:
        return {**hit[1], "cached": True}
    from app.core.ai.render import answer_html
    from app.modules.assistant.services import ask as ask_svc
    ans = ask_svc.ask(backend, agent, user, {**screen, "max_question": MAX_PROMPT}, prompt, None, True)
    kept = [sg for sg in ans.segments if not (sg["type"] == "text" and is_suggestions(sg["text"]))]
    ans.segments = kept or ans.segments
    out = {"html": alias.restore(answer_html(ans)), "secs": ans.secs,
           "asked_at": datetime.fromtimestamp(now, KST).strftime("%H:%M")}
    with _lock:
        _cache[ck] = (now, out)
        for k in [k for k, (t, _) in _cache.items() if now - t > CACHE_SECS]:
            _cache.pop(k, None)
    return {**out, "cached": False}
