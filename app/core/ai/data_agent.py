"""기존 BigQuery 데이터 에이전트(Conversational Analytics API) 연결.

- 숫자는 에이전트가 BigQuery 에 실행한 SQL 결과에서 나온다. 이 앱은 질문을 전달하고 답을 보여 줄 뿐이다.
- 인증: google.auth.default() — 내 PC 는 gcloud ADC(내 계정), Cloud Run 은 앱 서비스 계정.
- 응답 해석은 구글 시트 사이드바(AI_Agent.gs)와 같은 규칙: 추론(THOUGHT) 제외, 응답 순서대로 멘트·표, SQL 은 따로.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

API = "https://geminidataanalytics.googleapis.com/v1beta/"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
MAX_ROWS = 500


class DataAgentError(Exception):
    """화면에 그대로 보여 줄 수 있는 한국어 메시지."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Answer:
    segments: list[dict] = field(default_factory=list)   # {"type":"text","text":..} | {"type":"table","fields":[..],"rows":[..],"truncated":bool}
    sqls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    conversation: str | None = None
    mode: str = "conversation"
    secs: float = 0.0

    @property
    def text(self) -> str:
        return "\n\n".join(s["text"] for s in self.segments if s["type"] == "text").strip()


def error_text(status: int, body: str) -> str:
    t = body or ""
    if "SERVICE_DISABLED" in t or "has not been used in project" in t:
        return f"AI API 가 꺼져 있거나 사용량 프로젝트 설정이 맞지 않습니다 ({status}). AI_QUOTA_PROJECT 를 확인하세요."
    if status == 401:
        return "AI 인증이 만료됐습니다. 내 PC 라면 gcloud auth application-default login 을 다시 하세요. (401)"
    if status == 403:
        return ("AI 권한이 없습니다 (403). 실행 계정에 데이터 에이전트 사용자 권한과 해당 BigQuery 데이터 조회 권한이 필요합니다. "
                + t[:200])
    if status == 404:
        return "에이전트 또는 대화를 찾을 수 없습니다 (404). 에이전트 ID·게시 여부를 확인하세요."
    if status == 429:
        return "요청이 많습니다. 잠시 후 다시 시도해 주세요. (429)"
    if status in (500, 503, 504):
        return f"AI 서비스가 일시적으로 응답하지 않았습니다 ({status}). 잠시 후 다시 시도해 주세요."
    return f"AI 오류 {status}: {t[:300]}"


def clean_text(text: str) -> str:
    """시트 복붙용 블록(코드 블록·탭 구분 줄·'복붙/TSV' 안내 문구)만 뺀다. 표·설명은 그대로."""
    out, fence = [], False
    for line in str(text).replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence or "\t" in line:
            continue
        s = line.strip()
        if not s.startswith("|") and len(s) <= 80 and any(k in s for k in ("복붙", "복사", "붙여넣", "붙여 넣", "TSV", "시트용")):
            continue
        out.append(line)
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def parse(resp) -> Answer:
    """chat 응답(메시지 목록)을 순서대로 멘트·표 조각으로 나눈다."""
    ans = Answer()
    last = ""
    for m in resp if isinstance(resp, list) else [resp]:
        if not isinstance(m, dict):
            continue
        sm = m.get("systemMessage", m)
        t = sm.get("text") or {}
        parts = [p for p in (t.get("parts") or []) if isinstance(p, str)]
        if parts and t.get("textType", "") != "THOUGHT":
            s = clean_text("".join(parts))
            if s and s != last:
                ans.segments.append({"type": "text", "text": s})
                last = s
        d = sm.get("data") or {}
        if d.get("generatedSql"):
            ans.sqls.append(d["generatedSql"])
        res = d.get("result") or {}
        rows = res.get("data") or []
        if rows:
            fields = [f.get("name") for f in (res.get("schema") or {}).get("fields", [])] or list(rows[0].keys())
            ans.segments.append({"type": "table", "fields": fields, "rows": rows[:MAX_ROWS],
                                 "truncated": len(rows) > MAX_ROWS})
        if sm.get("error"):
            err = sm["error"]
            ans.notes.append("에이전트 오류: " + str(err.get("text") if isinstance(err, dict) else err)[:300])
        if sm.get("chart") and "차트는 BigQuery 콘솔 채팅에서만 보입니다." not in ans.notes:
            ans.notes.append("차트는 BigQuery 콘솔 채팅에서만 보입니다.")
    return ans


def conversation_prefix(email: str) -> str:
    """대화 ID 앞부분 — 사용자마다 달라서 남의 대화를 이어 쓰지 못하게 확인하는 데 쓴다."""
    return "a360-" + hashlib.sha256(email.lower().encode()).hexdigest()[:10] + "-"


class DataAgent:
    def __init__(self, project: str, location: str, agent_id: str, quota_project: str = "",
                 timeout: int = 280, session=None):
        self.project, self.location, self.agent_id = project, location, agent_id
        self.quota_project = quota_project or project
        self.timeout = timeout
        self._session = session

    @property
    def parent(self) -> str:
        return f"projects/{self.project}/locations/{self.location}"

    @property
    def agent_name(self) -> str:
        return f"{self.parent}/dataAgents/{self.agent_id}"

    # ── HTTP ─────────────────────────────────────
    def session(self):
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            creds, _ = google.auth.default(scopes=SCOPES)
            self._session = AuthorizedSession(creds)
        return self._session

    def _call(self, method: str, url: str, body: dict | None = None, timeout: int | None = None):
        headers = {"Content-Type": "application/json", "X-Goog-User-Project": self.quota_project}
        try:
            r = self.session().request(method, url, data=json.dumps(body) if body is not None else None,
                                       headers=headers, timeout=timeout or self.timeout)
        except Exception as e:  # noqa: BLE001  (인증 정보 없음·시간 초과 등)
            msg = str(e)
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                raise DataAgentError("AI 응답 대기 시간이 초과됐습니다. 기간·그룹을 줄여 다시 물어봐 주세요.", 504) from e
            if "credentials" in msg.lower():
                raise DataAgentError("AI 인증 정보가 없습니다. 내 PC 라면 gcloud auth application-default login 을 하세요.", 401) from e
            raise DataAgentError(f"AI 서비스에 연결하지 못했습니다: {msg[:200]}", 502) from e
        return r.status_code, r.text

    def _json(self, status: int, text: str):
        if status != 200:
            raise DataAgentError(error_text(status, text), status if status in (400, 401, 403, 404, 429) else 502)
        try:
            return json.loads(text)
        except ValueError as e:
            raise DataAgentError("AI 응답을 해석하지 못했습니다.", 502) from e

    # ── 기능 ─────────────────────────────────────
    def info(self) -> dict:
        """에이전트 정보 (연결 점검용, 조회 비용 없음)."""
        return self._json(*self._call("GET", API + self.agent_name, timeout=30))

    def new_conversation(self, prefix: str) -> str:
        cid = prefix + uuid.uuid4().hex[:16]
        status, text = self._call("POST", f"{API}{self.parent}/conversations?conversationId={cid}",
                                  {"agents": [self.agent_name]}, timeout=30)
        data = self._json(status, text)
        return data.get("name") or f"{self.parent}/conversations/{cid}"

    def _chat_body(self, question: str, conversation: str | None) -> dict:
        body = {"parent": self.parent, "messages": [{"userMessage": {"text": question}}]}
        if conversation:
            body["conversationReference"] = {"conversation": conversation,
                                             "dataAgentContext": {"dataAgent": self.agent_name}}
        else:
            body["dataAgentContext"] = {"dataAgent": self.agent_name}
        return body

    def chat(self, question: str, conversation: str | None = None) -> Answer:
        t0 = time.time()
        status, text = self._call("POST", f"{API}{self.parent}:chat", self._chat_body(question, conversation))
        ans = parse(self._json(status, text))
        ans.conversation = conversation
        ans.mode = "conversation" if conversation else "single"
        ans.secs = round(time.time() - t0, 1)
        return ans

    def ask(self, question: str, *, prefix: str, conversation: str | None = None, new: bool = False) -> Answer:
        """이어 묻기(대화)로 시도하고, 대화가 만료·오류면 새 대화 → 그래도 안 되면 한 번 묻기로 대신한다."""
        if conversation and not conversation.rsplit("/", 1)[-1].startswith(prefix):
            conversation = None                       # 남의 대화 ID 는 무시
        notes = []
        try:
            conv = None if new else conversation
            conv = conv or self.new_conversation(prefix)
            try:
                return self.chat(question, conv)
            except DataAgentError as e:
                if e.status not in (400, 404) or new or not conversation:
                    raise
                return self.chat(question, self.new_conversation(prefix))   # 저장된 대화가 만료됨
        except DataAgentError as e:
            if e.status in (401, 403, 429, 504):
                raise
            notes.append("이어 묻기 기능을 쓰지 못해 한 번 묻기로 처리했습니다.")
        ans = self.chat(question, None)
        ans.notes = notes + ans.notes
        return ans
