"""BigQueryBackend — 운영 데이터.

- 공통 데이터셋(COMMON_DATASET): fact_attendance, fact_qa, fact_training, fact_incentive
  → Capacity Web(기획안 2)과 같이 쓰는 데이터. 이 모듈은 읽기만 한다.
- KPI 데이터세트(KPI_DATASET): v_agent(상담사 목록 = INFO 재직자, 팀 = TL), v_agent_kpi_daily(v11 에서 매일 갱신)
- 모듈 데이터셋(MODULE_DATASET): user_roles, fact_coaching, mart_signals, signal_rules, issue_types, audit_log
테이블 정의는 sql/ddl/*.sql.

규칙
- SQL 은 항상 파라미터(@name)로. 문자열 이어 붙이기 금지.
- 팀이 있는 조회는 (@all_teams OR team IN UNNEST(@teams)) 로 권한 필터.
- 쓰기는 DML(INSERT/UPDATE). streaming insert 는 직후 UPDATE 가 막히므로 쓰지 않는다.
- 읽기는 CACHE_SECONDS 동안 메모리 캐시, 쓰기가 일어나면 캐시를 비운다.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime

from app.core.permissions import Scope

# 상담사 × 일자 KPI 열 (분자·분모 합 + 목표값) — 지표 계산은 app/modules/agent360/services/kpi.py
KPI_FIELDS = ("nps_net", "nps_responses", "solved_volume", "assignments", "reopens", "case_solves", "ttresp_min",
              "msg_sessions", "handle_sec", "work_sec", "cases_solved", "logged_min", "target_spd", "target_throughput",
              "target_reopen", "target_ttresp", "target_worktime")


class BigQueryBackend:
    def __init__(self, project: str, location: str, common_dataset: str, module_dataset: str, cache_seconds: int = 60,
                 kpi_dataset: str = "kpi"):
        from google.cloud import bigquery  # 지연 import: sample 모드에서는 패키지 없어도 됨

        self._bq = bigquery
        self.client = bigquery.Client(project=project or None)
        self.location = location
        self.c = f"`{self.client.project}.{common_dataset}`"
        self.m = f"`{self.client.project}.{module_dataset}`"
        self.k = f"`{self.client.project}.{kpi_dataset}`"
        self.agents_t = f"`{self.client.project}.{kpi_dataset}.v_agent`"
        self.ttl = cache_seconds
        self._cache: dict = {}
        self._lock = threading.Lock()

    # ── 공통 도우미 ────────────────────────────────
    def _params(self, params: dict):
        bq, out = self._bq, []
        for k, v in params.items():
            if isinstance(v, (list, tuple)):
                out.append(bq.ArrayQueryParameter(k, "STRING", [str(x) for x in v]))
            elif isinstance(v, bool):
                out.append(bq.ScalarQueryParameter(k, "BOOL", v))
            elif isinstance(v, int):
                out.append(bq.ScalarQueryParameter(k, "INT64", v))
            else:
                out.append(bq.ScalarQueryParameter(k, "STRING", None if v is None else str(v)))
        return out

    @staticmethod
    def _plain(v):
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, list):
            return [BigQueryBackend._plain(x) for x in v]
        return v

    def _q(self, sql: str, **params) -> list[dict]:
        job = self.client.query(sql, job_config=self._bq.QueryJobConfig(query_parameters=self._params(params)),
                                location=self.location)
        return [{k: self._plain(v) for k, v in dict(r).items()} for r in job.result()]

    def _cached(self, key: tuple, fn):
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        val = fn()
        with self._lock:
            self._cache[key] = (now, val)
        return val

    def _clear(self):
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _scope(scope: Scope) -> dict:
        return {"all_teams": scope.all_teams, "teams": list(scope.teams)}

    # ── 기준·마스터 ────────────────────────────────
    def as_of(self) -> str:
        # 기준일 = KPI 가 있는 마지막 날 다음 날 (그날까지가 집계 대상)
        rows = self._cached(("as_of",), lambda: self._q(
            f"SELECT CAST(DATE_ADD(MAX(date), INTERVAL 1 DAY) AS STRING) d FROM {self.k}.specialist_case_daily"))
        return (rows[0]["d"] if rows and rows[0]["d"] else date.today().isoformat())

    def get_user(self, email: str) -> dict | None:
        rows = self._cached(("user", email), lambda: self._q(
            f"SELECT email, name, role, teams FROM {self.m}.user_roles WHERE LOWER(email) = LOWER(@email) AND active",
            email=email))
        return rows[0] if rows else None

    def list_users(self) -> list[dict]:
        return self._q(f"SELECT email, name, role, teams FROM {self.m}.user_roles WHERE active ORDER BY role, email")

    def list_teams(self) -> list[dict]:
        return self._cached(("teams",), lambda: self._q(
            f"""SELECT team, ANY_VALUE(team_label) AS label, APPROX_TOP_COUNT(sector, 1)[SAFE_OFFSET(0)].value AS sector
                FROM {self.agents_t} WHERE status = '재직' GROUP BY team ORDER BY label"""))

    def list_agents(self, scope: Scope, q: str | None = None, team: str | None = None) -> list[dict]:
        sql = f"""
          SELECT agent_id, ldap, name, team, sv_email, CAST(hire_date AS STRING) hire_date, cohort,
                 CAST(nesting_end AS STRING) nesting_end, skill_tags, status
          FROM {self.agents_t}
          WHERE status = '재직'
            AND (@all_teams OR team IN UNNEST(@teams))
            AND (@team IS NULL OR team = @team)
            AND (@q IS NULL OR LOWER(name) LIKE CONCAT('%', LOWER(@q), '%')
                 OR LOWER(agent_id) LIKE CONCAT('%', LOWER(@q), '%') OR LOWER(IFNULL(ldap, '')) LIKE CONCAT('%', LOWER(@q), '%'))
          ORDER BY team, name"""
        p = dict(self._scope(scope), team=team or None, q=(q or "").strip() or None)
        return self._cached(("agents", json.dumps(p, sort_keys=True)), lambda: self._q(sql, **p))

    def get_agent(self, scope: Scope, agent_id: str) -> dict | None:
        rows = [a for a in self.list_agents(scope) if a["agent_id"] == agent_id]
        return rows[0] if rows else None

    # ── 사실 데이터 ────────────────────────────────
    def _fact(self, table: str, cols: str, agent_id: str, since: str | None, order: str):
        where = "agent_id = @agent_id" + (" AND date >= DATE(@since)" if since else "")
        sql = f"SELECT {cols} FROM {self.c}.{table} WHERE {where} ORDER BY {order}"
        return self._cached((table, agent_id, since), lambda: self._q(sql, agent_id=agent_id, since=since))

    def kpi_daily(self, agent_id, since):
        sql = f"""SELECT agent_id, CAST(date AS STRING) date, tenure_group, {", ".join(KPI_FIELDS)}
                   FROM {self.k}.v_agent_kpi_daily
                   WHERE agent_id = @agent_id AND (@since IS NULL OR date >= DATE(@since)) ORDER BY date"""
        return self._cached(("kpi", agent_id, since), lambda: self._q(sql, agent_id=agent_id, since=since))

    def kpi_daily_many(self, agent_ids, since):
        sql = f"""SELECT agent_id, CAST(date AS STRING) date, tenure_group, {", ".join(KPI_FIELDS)}
                  FROM {self.k}.v_agent_kpi_daily
                  WHERE agent_id IN UNNEST(@ids) AND date >= DATE(@since) ORDER BY agent_id, date"""
        ids = sorted(set(agent_ids))
        rows = self._cached(("kpi_many", tuple(ids), since), lambda: self._q(sql, ids=ids, since=since)) if ids else []
        out: dict[str, list[dict]] = {a: [] for a in agent_ids}
        for r in rows:
            out.setdefault(r["agent_id"], []).append(r)
        return out

    def attendance(self, agent_id, since):
        return self._fact("fact_attendance", "agent_id, CAST(date AS STRING) date, status", agent_id, since, "date")

    def qa(self, agent_id, since):
        return self._fact("fact_qa", "qa_id, agent_id, CAST(date AS STRING) date, score, error_types", agent_id, since, "date DESC")

    def training(self, agent_id):
        sql = f"""SELECT agent_id, course, kind, CAST(completed_on AS STRING) completed_on
                  FROM {self.c}.fact_training WHERE agent_id = @agent_id ORDER BY completed_on DESC"""
        return self._cached(("training", agent_id), lambda: self._q(sql, agent_id=agent_id))

    def incentive(self, agent_id):
        sql = f"""SELECT agent_id, month, grade, note FROM {self.c}.fact_incentive
                  WHERE agent_id = @agent_id ORDER BY month DESC LIMIT 6"""
        return self._cached(("incentive", agent_id), lambda: self._q(sql, agent_id=agent_id))

    # ── 코칭 ───────────────────────────────────────
    def coaching(self, scope: Scope, agent_id: str | None = None) -> list[dict]:
        sql = f"""
          SELECT c.coaching_id, c.agent_id, c.sv_email, CAST(c.date AS STRING) date, c.issue_type, c.summary,
                 c.agreed_action, CAST(c.follow_up_date AS STRING) follow_up_date, c.done,
                 CAST(c.done_at AS STRING) done_at, c.raw_note, a.team
          FROM {self.m}.fact_coaching c JOIN {self.agents_t} a USING (agent_id)
          WHERE (@all_teams OR a.team IN UNNEST(@teams)) AND (@agent_id IS NULL OR c.agent_id = @agent_id)
          ORDER BY c.date DESC, c.coaching_id DESC"""
        p = dict(self._scope(scope), agent_id=agent_id)
        return self._cached(("coaching", json.dumps(p, sort_keys=True)), lambda: self._q(sql, **p))

    def add_coaching(self, record: dict) -> dict:
        rec = {"coaching_id": "C" + uuid.uuid4().hex[:10].upper(), "done": False, "done_at": None, **record}
        self._q(f"""
          INSERT INTO {self.m}.fact_coaching
            (coaching_id, agent_id, sv_email, date, issue_type, summary, agreed_action, follow_up_date, done, raw_note, created_at)
          VALUES (@coaching_id, @agent_id, @sv_email, DATE(@date), @issue_type, @summary, @agreed_action,
                  DATE(@follow_up_date), FALSE, @raw_note, CURRENT_TIMESTAMP())""",
                **{k: rec.get(k) for k in ("coaching_id", "agent_id", "sv_email", "date", "issue_type", "summary",
                                           "agreed_action", "follow_up_date", "raw_note")})
        self._clear()
        return rec

    def complete_coaching(self, coaching_id: str, by: str) -> dict | None:
        self._q(f"""UPDATE {self.m}.fact_coaching SET done = TRUE, done_at = CURRENT_DATE('Asia/Seoul'), done_by = @by
                    WHERE coaching_id = @id""", id=coaching_id, by=by)
        self._clear()
        rows = self._q(f"SELECT coaching_id, agent_id, done FROM {self.m}.fact_coaching WHERE coaching_id = @id", id=coaching_id)
        return rows[0] if rows else None

    # ── 신호 ───────────────────────────────────────
    def signals(self, scope: Scope, as_of: str | None = None) -> list[dict]:
        as_of = as_of or self.as_of()
        sql = f"""
          SELECT s.signal_id, CAST(s.as_of AS STRING) as_of, s.agent_id, s.type, s.label, s.severity, s.score,
                 s.evidence, s.status, a.team
          FROM {self.m}.mart_signals s JOIN {self.agents_t} a USING (agent_id)
          WHERE s.as_of = DATE(@as_of) AND (@all_teams OR a.team IN UNNEST(@teams))"""
        p = dict(self._scope(scope), as_of=as_of)
        return self._cached(("signals", json.dumps(p, sort_keys=True)), lambda: self._q(sql, **p))

    def set_signal_status(self, signal_id: str, status: str, by: str) -> dict | None:
        self._q(f"""UPDATE {self.m}.mart_signals SET status = @status, status_by = @by, status_at = CURRENT_TIMESTAMP()
                    WHERE signal_id = @id""", id=signal_id, status=status, by=by)
        self._clear()
        rows = self._q(f"""SELECT s.signal_id, s.agent_id, s.status, a.team FROM {self.m}.mart_signals s
                           JOIN {self.agents_t} a USING (agent_id) WHERE s.signal_id = @id""", id=signal_id)
        return rows[0] if rows else None

    def signal_rules(self) -> list[dict]:
        rows = self._cached(("rules",), lambda: self._q(
            f"SELECT rule, label, severity, description, params FROM {self.m}.signal_rules ORDER BY rule"))
        for r in rows:
            if isinstance(r.get("params"), str):
                r["params"] = json.loads(r["params"] or "{}")
        return rows

    def issue_types(self) -> list[str]:
        rows = self._cached(("issue_types",), lambda: self._q(
            f"SELECT issue_type FROM {self.m}.issue_types WHERE active ORDER BY sort_order"))
        return [r["issue_type"] for r in rows]

    # ── 감사 로그 ──────────────────────────────────
    def write_audit(self, event: dict) -> None:
        self._q(f"""INSERT INTO {self.m}.audit_log (ts, actor, role, action, target_type, target_id, detail)
                    VALUES (TIMESTAMP(@ts), @actor, @role, @action, @target_type, @target_id, PARSE_JSON(@detail))""",
                ts=event["ts"], actor=event["actor"], role=event["role"], action=event["action"],
                target_type=event["target_type"], target_id=event["target_id"],
                detail=json.dumps(event.get("detail") or {}, ensure_ascii=False))
