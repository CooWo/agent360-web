"""샘플 데이터 생성기 (실데이터 권한이 나오기 전 화면 개발용).

python sample_data/generate.py            # 오늘 기준으로 다시 생성
python sample_data/generate.py 2026-11-20 # 기준일 지정

- 모든 값은 가짜다. 이메일은 example.com, 이름은 임의 조합.
- 테이블 모양은 기획안 5장(dim_agent, fact_*, fact_coaching, mart_signals)을 따른다.
- 신호는 기획안 6-1 규칙을 단순하게 계산해 넣는다. (실제 운영은 sql/signals 의 SQL 배치가 만든다)
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
SEED = 360

TEAMS = [
    {"team": "R1-A", "label": "R1 A팀", "sector": "Resolutions 1"},
    {"team": "R1-B", "label": "R1 B팀", "sector": "Resolutions 1"},
    {"team": "R2-A", "label": "R2 A팀", "sector": "Resolutions 2"},
]
USERS = [
    {"email": "admin@example.com", "name": "관리자", "role": "admin", "teams": []},
    {"email": "manager@example.com", "name": "최매니저", "role": "manager", "teams": []},
    {"email": "sv.kim@example.com", "name": "김SV", "role": "sv", "teams": ["R1-A"]},
    {"email": "sv.lee@example.com", "name": "이SV", "role": "sv", "teams": ["R1-B"]},
    {"email": "sv.park@example.com", "name": "박SV", "role": "sv", "teams": ["R2-A"]},
    {"email": "viewer@example.com", "name": "조회자", "role": "viewer", "teams": ["R1-A", "R1-B"]},
]
SV_OF_TEAM = {"R1-A": "sv.kim@example.com", "R1-B": "sv.lee@example.com", "R2-A": "sv.park@example.com"}

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = ["민준", "서연", "지호", "하은", "도윤", "수아", "예준", "지유", "시우", "채원",
         "주원", "다은", "하준", "윤서", "지안", "서진", "유진", "현우", "소윤", "은우"]
SKILLS = ["환불", "취소", "온트립", "호스트", "결제", "일본어", "영어", "에스컬레이션"]
QA_ERRORS = ["환불 정책 오안내", "본인 확인 누락", "케이스 메모 미흡", "공감 표현 부족", "에스컬레이션 기준 위반", "템플릿 오사용"]
ISSUE_TYPES = ["정책 오안내", "프로세스 미준수", "응대 태도", "처리 속도(AHT)", "근태", "품질(QA) 오류", "시스템·툴 사용", "기타"]

RULES = [
    {"rule": "kpi_drop", "label": "KPI 급락", "severity": "중",
     "description": "최근 2주 평균이 본인 직전 8주 평균보다 기준% 이상 나빠짐 (처리 건수·NPS)", "params": {"drop_pct": 15}},
    {"rule": "absence_pattern", "label": "결근 패턴", "severity": "중",
     "description": "30일 내 결근 기준 횟수 이상", "params": {"absences_30d": 3}},
    {"rule": "qa_repeat", "label": "QA 반복 오류", "severity": "상",
     "description": "같은 오류 유형이 30일 내 기준 횟수 이상", "params": {"repeat_30d": 2}},
    {"rule": "coaching_overdue", "label": "코칭 후속 미이행", "severity": "중",
     "description": "후속 확인일 경과 + 미완료", "params": {}},
    {"rule": "new_hire", "label": "신입 주의", "severity": "중",
     "description": "네스팅 종료 기준일 이내 + 처리 건수가 기수 평균 미만", "params": {"weeks_after_nesting": 4}},
    {"rule": "no_coaching", "label": "장기 미코칭", "severity": "하",
     "description": "마지막 코칭 후 기준일 경과 (코칭 이력 없음 포함)", "params": {"days": 45}},
]
SEVERITY_SCORE = {"상": 3, "중": 2, "하": 1}


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main(as_of: date) -> None:
    rnd = random.Random(SEED)
    start = as_of - timedelta(days=69)                     # 10주
    days = list(weekdays(start, as_of - timedelta(days=1)))  # 어제까지

    # ── 상담사 마스터 ───────────────────────────────
    agents = []
    used = set()
    n = 0
    for t in TEAMS:
        for _ in range(10):
            n += 1
            while True:
                name = rnd.choice(SURNAMES) + rnd.choice(GIVEN)
                if name not in used:
                    used.add(name)
                    break
            new_hire = n in (4, 15, 27)
            hire = as_of - timedelta(days=rnd.randint(40, 55) if new_hire else rnd.randint(200, 1400))
            nesting_end = hire + timedelta(days=28)
            agents.append({
                "agent_id": f"E24{n:04d}",
                "ldap": f"ub_sample{n:02d}",
                "name": name,
                "team": t["team"],
                "sv_email": SV_OF_TEAM[t["team"]],
                "hire_date": hire.isoformat(),
                "cohort": f"{hire.year % 100}-{(hire.month - 1) // 3 + 1}기",
                "nesting_end": nesting_end.isoformat(),
                "skill_tags": rnd.sample(SKILLS, k=rnd.randint(1, 3)),
                "status": "재직",
            })

    # 문제 패턴을 일부러 심는 상담사
    drop = {"E240002", "E240013", "E240022"}
    absent = {"E240007", "E240019"}
    qa_rep = {"E240003", "E240024"}

    # ── KPI 일별 ───────────────────────────────────
    kpi = []
    for a in agents:
        base_h = rnd.uniform(32, 44)
        base_aht = rnd.uniform(520, 760)
        base_nps = rnd.uniform(62, 85)
        is_new = date.fromisoformat(a["nesting_end"]) > as_of - timedelta(days=28)
        for d in days:
            if d < date.fromisoformat(a["hire_date"]):
                continue
            recent = (as_of - d).days <= 14
            f = 0.75 if (a["agent_id"] in drop and recent) else 1.0
            ramp = 0.7 if is_new else 1.0
            handled = max(5, round(rnd.gauss(base_h * f * ramp, 4)))
            aht = round(rnd.gauss(base_aht / (f if f < 1 else 1), 45))
            resp = rnd.randint(2, 7)
            nps_t = base_nps - (25 if (a["agent_id"] in drop and recent) else 0)
            prom = sum(1 for _ in range(resp) if rnd.random() < (nps_t / 100 + 1) / 2 * 0.95)
            det = sum(1 for _ in range(resp - prom) if rnd.random() < 0.6)
            kpi.append({"agent_id": a["agent_id"], "date": d.isoformat(), "handled": handled,
                        "aht_sec": aht, "nps_responses": resp, "nps_net": prom - det,
                        "productivity": round(handled / 7.5, 2)})

    # ── 근태 ───────────────────────────────────────
    att = []
    for a in agents:
        for d in days:
            if d < date.fromisoformat(a["hire_date"]):
                continue
            r = rnd.random()
            st = "정상"
            if a["agent_id"] in absent and (as_of - d).days <= 30 and d.weekday() in (0, 4) and r < 0.45:
                st = "결근"
            elif r < 0.015:
                st = "결근"
            elif r < 0.04:
                st = "지각"
            elif r < 0.07:
                st = "연차"
            att.append({"agent_id": a["agent_id"], "date": d.isoformat(), "status": st})

    # ── QA ─────────────────────────────────────────
    qa = []
    q = 0
    for a in agents:
        for d in days[::10]:
            if d < date.fromisoformat(a["hire_date"]):
                continue
            q += 1
            errs = []
            if a["agent_id"] in qa_rep and (as_of - d).days <= 30:
                errs = ["환불 정책 오안내"]
            elif rnd.random() < 0.35:
                errs = [rnd.choice(QA_ERRORS)]
            score = round(rnd.uniform(86, 98) - 6 * len(errs), 1)
            qa.append({"qa_id": f"QA{q:05d}", "agent_id": a["agent_id"], "date": d.isoformat(),
                       "score": score, "error_types": errs})

    # ── 교육 ───────────────────────────────────────
    training = []
    for a in agents:
        h = date.fromisoformat(a["hire_date"])
        training.append({"agent_id": a["agent_id"], "course": "입문 교육", "kind": "입문", "completed_on": (h + timedelta(days=10)).isoformat()})
        training.append({"agent_id": a["agent_id"], "course": "네스팅", "kind": "네스팅", "completed_on": a["nesting_end"]})
        for s in a["skill_tags"][:2]:
            c = h + timedelta(days=rnd.randint(40, 300))
            if c < as_of:
                training.append({"agent_id": a["agent_id"], "course": f"{s} 스킬 인증", "kind": "스킬 인증", "completed_on": c.isoformat()})

    # ── 인센티브 (월) ──────────────────────────────
    incentive = []
    for a in agents:
        for k in range(1, 4):
            m = (as_of.replace(day=1) - timedelta(days=1)).replace(day=1)
            for _ in range(k - 1):
                m = (m - timedelta(days=1)).replace(day=1)
            incentive.append({"agent_id": a["agent_id"], "month": m.strftime("%Y-%m"),
                              "grade": rnd.choices(["S", "A", "B", "C"], [1, 4, 4, 1])[0],
                              "note": "처리 건수·NPS·QA 가중 합산"})

    # ── 코칭 기록 ──────────────────────────────────
    coaching = []
    c = 0
    for a in agents:
        k = rnd.randint(0, 3)
        if a["agent_id"] in {"E240009", "E240018"}:
            k = 0                                            # 장기 미코칭 예시
        for _ in range(k):
            c += 1
            d = as_of - timedelta(days=rnd.randint(5, 80))
            fu = d + timedelta(days=rnd.choice([7, 10, 14]))
            done = fu < as_of and rnd.random() < 0.7
            issue = rnd.choice(ISSUE_TYPES[:6])
            coaching.append({
                "coaching_id": f"C{c:05d}", "agent_id": a["agent_id"], "sv_email": a["sv_email"],
                "date": d.isoformat(), "issue_type": issue,
                "summary": f"{issue} 관련 사례 2건 함께 확인", "agreed_action": "관련 KB 재숙지 후 유사 케이스 3건 셀프 점검",
                "follow_up_date": fu.isoformat(), "done": done,
                "done_at": (fu.isoformat() if done else None), "raw_note": "",
            })

    # ── 신호 (기획안 6-1 단순 계산) ───────────────
    p = {r["rule"]: r["params"] for r in RULES}
    sev = {r["rule"]: r["severity"] for r in RULES}
    label = {r["rule"]: r["label"] for r in RULES}
    by_agent = defaultdict(list)
    for r in kpi:
        by_agent[r["agent_id"]].append(r)
    cohort_recent = defaultdict(list)
    signals = []

    def add(agent_id, rule, evidence):
        signals.append({"signal_id": f"S{len(signals) + 1:05d}", "as_of": as_of.isoformat(), "agent_id": agent_id,
                        "type": rule, "label": label[rule], "severity": sev[rule],
                        "score": SEVERITY_SCORE[sev[rule]], "evidence": evidence, "status": "미확인"})

    def avg(xs):
        return sum(xs) / len(xs) if xs else None

    recent_h = {}
    for a in agents:
        rows = by_agent[a["agent_id"]]
        rec = [r for r in rows if (as_of - date.fromisoformat(r["date"])).days <= 14]
        pri = [r for r in rows if 14 < (as_of - date.fromisoformat(r["date"])).days <= 70]
        recent_h[a["agent_id"]] = avg([r["handled"] for r in rec])
        cohort_recent[a["cohort"]].append(recent_h[a["agent_id"]] or 0)
        if rec and pri:
            h1, h0 = avg([r["handled"] for r in rec]), avg([r["handled"] for r in pri])
            n1 = sum(r["nps_net"] for r in rec) / max(1, sum(r["nps_responses"] for r in rec)) * 100
            n0 = sum(r["nps_net"] for r in pri) / max(1, sum(r["nps_responses"] for r in pri)) * 100
            dh = (h1 - h0) / h0 * 100
            if dh <= -p["kpi_drop"]["drop_pct"]:
                add(a["agent_id"], "kpi_drop", f"처리 건수 최근 2주 평균 {h1:.1f}건 · 직전 8주 {h0:.1f}건 ({dh:+.0f}%)")
            elif n0 > 0 and (n1 - n0) / n0 * 100 <= -p["kpi_drop"]["drop_pct"]:
                add(a["agent_id"], "kpi_drop", f"NPS 최근 2주 {n1:.0f} · 직전 8주 {n0:.0f} ({n1 - n0:+.0f}점)")

    for a in agents:
        ab = [r for r in att if r["agent_id"] == a["agent_id"] and r["status"] == "결근"
              and (as_of - date.fromisoformat(r["date"])).days <= 30]
        if len(ab) >= p["absence_pattern"]["absences_30d"]:
            wd = Counter(date.fromisoformat(r["date"]).weekday() for r in ab)
            mf = wd[0] + wd[4]
            add(a["agent_id"], "absence_pattern", f"30일 내 결근 {len(ab)}회 (월·금 {mf}회)")

        errs = Counter(e for r in qa if r["agent_id"] == a["agent_id"]
                       and (as_of - date.fromisoformat(r["date"])).days <= 30 for e in r["error_types"])
        for e, cnt in errs.items():
            if cnt >= p["qa_repeat"]["repeat_30d"]:
                add(a["agent_id"], "qa_repeat", f"'{e}' 30일 내 {cnt}회")

        mine = [x for x in coaching if x["agent_id"] == a["agent_id"]]
        for x in mine:
            if not x["done"] and date.fromisoformat(x["follow_up_date"]) < as_of:
                add(a["agent_id"], "coaching_overdue", f"{x['date']} 코칭 후속 확인일 {x['follow_up_date']} 경과")
        last = max((date.fromisoformat(x["date"]) for x in mine), default=None)
        if last is None:
            add(a["agent_id"], "no_coaching", "코칭 이력 없음")
        elif (as_of - last).days >= p["no_coaching"]["days"]:
            add(a["agent_id"], "no_coaching", f"마지막 코칭 {last.isoformat()} ({(as_of - last).days}일 경과)")

        ne = date.fromisoformat(a["nesting_end"])
        if 0 <= (as_of - ne).days <= p["new_hire"]["weeks_after_nesting"] * 7:
            ca = avg([v for v in cohort_recent[a["cohort"]] if v]) or 0
            mine_h = recent_h.get(a["agent_id"]) or 0
            team_avg = avg([recent_h[x["agent_id"]] for x in agents if x["team"] == a["team"] and recent_h[x["agent_id"]]])
            ref = team_avg or ca
            if mine_h < ref:
                add(a["agent_id"], "new_hire", f"네스팅 종료 {ne.isoformat()} · 최근 2주 처리 {mine_h:.1f}건 (팀 평균 {ref:.1f}건)")

    files = {
        "meta": {"as_of": as_of.isoformat(), "account": "Airbnb KR (샘플)", "generated_by": "sample_data/generate.py"},
        "teams": TEAMS, "users": USERS, "agents": agents, "kpi_daily": kpi, "attendance": att, "qa": qa,
        "training": training, "incentive": incentive, "coaching": coaching, "signals": signals,
        "signal_rules": RULES, "issue_types": ISSUE_TYPES,
    }
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"as_of={as_of} agents={len(agents)} kpi={len(kpi)} signals={len(signals)} coaching={len(coaching)}")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today())
