"""SampleBackend — sample_data/*.json 을 메모리에 올려 쓴다.

화면에서 바꾼 내용(코칭 저장, 신호 처리, 감사 로그)은 sample_data/runtime/ 에 따로 저장해
재시작해도 남고, 원본 샘플은 건드리지 않는다. (runtime 폴더를 지우면 초기 상태로)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.permissions import Scope


class SampleBackend:
    def __init__(self, sample_dir: Path):
        self.dir = Path(sample_dir)
        self.runtime = self.dir / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        load = lambda n: json.loads((self.dir / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
        self.meta = load("meta")
        self._teams = load("teams")
        self._users = {u["email"].lower(): u for u in load("users")}
        self._agents = {a["agent_id"]: a for a in load("agents")}
        self._kpi = load("kpi_daily")
        self._att = load("attendance")
        self._qa = load("qa")
        self._training = load("training")
        self._incentive = load("incentive")
        self._coaching = load("coaching") + self._read_runtime("coaching_added", [])
        self._signals = load("signals")
        self._rules = load("signal_rules")
        self._issue_types = load("issue_types")
        # runtime 반영
        for cid, patch in self._read_runtime("coaching_patch", {}).items():
            for c in self._coaching:
                if c["coaching_id"] == cid:
                    c.update(patch)
        for sid, st in self._read_runtime("signal_status", {}).items():
            for s in self._signals:
                if s["signal_id"] == sid:
                    s.update(st)

    # ── runtime 저장 도우미 ─────────────────────────
    def _read_runtime(self, name, default):
        p = self.runtime / f"{name}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def _write_runtime(self, name, data):
        (self.runtime / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _team_of(self, agent_id: str) -> str | None:
        a = self._agents.get(agent_id)
        return a["team"] if a else None

    # ── 기준·마스터 ────────────────────────────────
    def as_of(self) -> str:
        return self.meta["as_of"]

    def get_user(self, email: str) -> dict | None:
        return self._users.get((email or "").lower())

    def list_users(self) -> list[dict]:
        return list(self._users.values())

    def list_teams(self) -> list[dict]:
        return list(self._teams)

    def list_agents(self, scope: Scope, q: str | None = None, team: str | None = None) -> list[dict]:
        rows = scope.filter(list(self._agents.values()))
        if team:
            rows = [a for a in rows if a["team"] == team]
        if q:
            ql = q.strip().lower()
            rows = [a for a in rows if ql in a["name"].lower() or ql in a["agent_id"].lower() or ql in (a.get("ldap") or "").lower()]
        return sorted(rows, key=lambda a: (a["team"], a["name"]))

    def get_agent(self, scope: Scope, agent_id: str) -> dict | None:
        a = self._agents.get(agent_id)
        return a if a and scope.allows(a["team"]) else None

    # ── 사실 데이터 ────────────────────────────────
    def kpi_daily(self, agent_id, since):
        return [r for r in self._kpi if r["agent_id"] == agent_id and r["date"] >= since]

    def kpi_daily_many(self, agent_ids, since):
        want = set(agent_ids)
        out: dict[str, list[dict]] = {a: [] for a in agent_ids}
        for r in self._kpi:
            if r["agent_id"] in want and r["date"] >= since:
                out[r["agent_id"]].append(r)
        return out

    def attendance(self, agent_id, since):
        return [r for r in self._att if r["agent_id"] == agent_id and r["date"] >= since]

    def qa(self, agent_id, since):
        return sorted([r for r in self._qa if r["agent_id"] == agent_id and r["date"] >= since], key=lambda r: r["date"], reverse=True)

    def training(self, agent_id):
        return sorted([r for r in self._training if r["agent_id"] == agent_id], key=lambda r: r["completed_on"], reverse=True)

    def incentive(self, agent_id):
        return sorted([r for r in self._incentive if r["agent_id"] == agent_id], key=lambda r: r["month"], reverse=True)

    # ── 코칭 ───────────────────────────────────────
    def coaching(self, scope: Scope, agent_id: str | None = None) -> list[dict]:
        rows = [dict(c, team=self._team_of(c["agent_id"])) for c in self._coaching]
        rows = scope.filter(rows)
        if agent_id:
            rows = [c for c in rows if c["agent_id"] == agent_id]
        return sorted(rows, key=lambda c: (c["date"], c["coaching_id"]), reverse=True)

    def add_coaching(self, record: dict) -> dict:
        with self._lock:
            n = max([int(c["coaching_id"][1:]) for c in self._coaching] or [0]) + 1
            rec = {"coaching_id": f"C{n:05d}", "done": False, "done_at": None, **record}
            self._coaching.append(rec)
            added = self._read_runtime("coaching_added", [])
            added.append(rec)
            self._write_runtime("coaching_added", added)
        return rec

    def complete_coaching(self, coaching_id: str, by: str) -> dict | None:
        with self._lock:
            for c in self._coaching:
                if c["coaching_id"] == coaching_id:
                    patch = {"done": True, "done_at": datetime.now(timezone.utc).date().isoformat(), "done_by": by}
                    c.update(patch)
                    p = self._read_runtime("coaching_patch", {})
                    p[coaching_id] = patch
                    self._write_runtime("coaching_patch", p)
                    added = self._read_runtime("coaching_added", [])
                    if any(x["coaching_id"] == coaching_id for x in added):
                        for x in added:
                            if x["coaching_id"] == coaching_id:
                                x.update(patch)
                        self._write_runtime("coaching_added", added)
                    return c
        return None

    # ── 신호 ───────────────────────────────────────
    def signals(self, scope: Scope, as_of: str | None = None) -> list[dict]:
        as_of = as_of or self.as_of()
        rows = [dict(s, team=self._team_of(s["agent_id"])) for s in self._signals if s["as_of"] == as_of]
        return scope.filter(rows)

    def set_signal_status(self, signal_id: str, status: str, by: str) -> dict | None:
        with self._lock:
            for s in self._signals:
                if s["signal_id"] == signal_id:
                    patch = {"status": status, "status_by": by,
                             "status_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                    s.update(patch)
                    p = self._read_runtime("signal_status", {})
                    p[signal_id] = patch
                    self._write_runtime("signal_status", p)
                    return dict(s, team=self._team_of(s["agent_id"]))
        return None

    def signal_rules(self) -> list[dict]:
        return list(self._rules)

    def issue_types(self) -> list[str]:
        return list(self._issue_types)

    # ── 감사 로그 ──────────────────────────────────
    def write_audit(self, event: dict) -> None:
        with self._lock, open(self.runtime / "audit_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
