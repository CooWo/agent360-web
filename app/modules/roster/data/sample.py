"""RosterSample — sample_data/roster/*.json. 적용한 버전·초안은 sample_data/runtime/roster_*.json (원본은 그대로)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class RosterSample:
    def __init__(self, sample_dir: str | Path):
        d = Path(sample_dir) / "roster"
        self._info = json.loads((d / "agent_info.json").read_text(encoding="utf-8"))
        self._base = json.loads((d / "board.json").read_text(encoding="utf-8"))
        rt = Path(sample_dir) / "runtime"
        rt.mkdir(parents=True, exist_ok=True)
        self._versions_path, self._drafts_path = rt / "roster_versions.json", rt / "roster_drafts.json"
        self._lock = threading.Lock()

    def _read(self, p: Path, default):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def _write(self, p: Path, data) -> None:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def agent_info(self) -> list[dict]:
        return [dict(r) for r in self._info]

    def info_loads(self, limit: int = 10) -> list[dict]:
        return [{"load_id": "SAMPLE", "loaded_at": "2026-11-20T00:00:00+00:00", "loaded_by": "sample_data",
                 "source": "sample_data/roster/agent_info.json", "rows_read": len(self._info),
                 "rows_mart": len(self._info), "dropped_no_id": 0, "duplicates": 0, "issues": 0}][:limit]

    def board(self) -> list[dict]:
        vs = self._read(self._versions_path, [])
        return [dict(r) for r in (vs[-1]["rows"] if vs else self._base)]

    def save_board(self, rows: list[dict], by: str) -> str:
        with self._lock:
            vs = self._read(self._versions_path, [])
            vid = "V" + uuid.uuid4().hex[:10]
            vs.append({"version_id": vid, "saved_at": _now(), "saved_by": by, "rows": [dict(r) for r in rows]})
            self._write(self._versions_path, vs)
        return vid

    def versions(self, limit: int = 20) -> list[dict]:
        vs = self._read(self._versions_path, [])
        return [{k: v[k] for k in ("version_id", "saved_at", "saved_by")} | {"count": len(v["rows"])}
                for v in reversed(vs)][:limit]

    def draft(self, email: str) -> dict | None:
        return self._read(self._drafts_path, {}).get(email.lower())

    def save_draft(self, email: str, rows: list[dict]) -> dict:
        with self._lock:
            ds = self._read(self._drafts_path, {})
            d = {"saved_at": _now(), "rows": [dict(r) for r in rows]}
            ds[email.lower()] = d
            self._write(self._drafts_path, ds)
        return d

    def clear_draft(self, email: str) -> None:
        with self._lock:
            ds = self._read(self._drafts_path, {})
            if ds.pop(email.lower(), None) is not None:
                self._write(self._drafts_path, ds)
