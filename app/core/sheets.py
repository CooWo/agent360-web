"""구글 시트 읽기 — 값만 (서식 없이). 웹 서버와 동기화 스크립트가 같이 쓴다.

자격 증명은 실행 환경의 기본 계정(ADC)을 쓴다.
- 내 PC: gcloud auth application-default login --scopes=...spreadsheets.readonly,...cloud-platform
- Cloud Run: 앱 서비스 계정에 시트를 '보기 권한'으로 공유
읽는 방법을 바꾸려면(예: CSV 내보내기) SheetReader 를 하나 더 만든다.
"""
from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/cloud-platform"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/cloud-platform"]


class SheetAccessError(Exception):
    pass


class SheetReader(Protocol):
    def values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]: ...


class GoogleSheetReader:
    def __init__(self, session=None):
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            cred, _ = google.auth.default(scopes=SCOPES)
            session = AuthorizedSession(cred)
        self.s = session

    def values(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quote(a1_range)}"
               "?valueRenderOption=FORMATTED_VALUE&majorDimension=ROWS")
        r = self.s.get(url, timeout=60)
        if r.status_code == 403:
            raise SheetAccessError("시트를 읽을 권한이 없습니다. 내 PC 는 'gcloud auth application-default login "
                                   "--scopes=...spreadsheets.readonly' 로 다시 로그인, 서버는 서비스 계정에 시트 공유가 필요합니다.")
        if r.status_code == 404:
            raise SheetAccessError("시트 또는 탭을 찾을 수 없습니다.")
        r.raise_for_status()
        return r.json().get("values", [])


class SheetWriter(Protocol):
    def append(self, spreadsheet_id: str, a1_range: str, rows: list[list[str]]) -> int: ...
    def update_many(self, spreadsheet_id: str, data: list[tuple[str, list[list[str]]]]) -> int: ...


def safe_cell(v) -> str:
    """시트에 쓸 값 — '=' '+' '-' '@' 로 시작하면 수식으로 읽히지 않게 앞에 ' 를 붙인다."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


class GoogleSheetWriter:
    """표 맨 아래에 줄 더하기 (values.append, INSERT_ROWS). 서버 서비스 계정에 시트 '편집자' 공유가 필요하다."""

    def __init__(self, session=None):
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            cred, _ = google.auth.default(scopes=WRITE_SCOPES)
            session = AuthorizedSession(cred)
        self.s = session

    def append(self, spreadsheet_id: str, a1_range: str, rows: list[list[str]]) -> int:
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quote(a1_range)}:append"
               "?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS")
        r = self.s.post(url, json={"values": [[safe_cell(c) for c in row] for row in rows]}, timeout=60)
        if r.status_code == 403:
            raise SheetAccessError("시트에 쓸 권한이 없습니다. 원본 시트를 서버 서비스 계정에 '편집자'로 공유해 주세요.")
        if r.status_code == 404:
            raise SheetAccessError("시트 또는 탭을 찾을 수 없습니다.")
        r.raise_for_status()
        return int(r.json().get("updates", {}).get("updatedRows", len(rows)))

    def update_many(self, spreadsheet_id: str, data: list[tuple[str, list[list[str]]]]) -> int:
        """여러 범위의 칸 값을 한 번에 바꾸기 (values.batchUpdate). 서식은 그대로 둔다. 바꾼 칸 수를 돌려준다."""
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate"
        body = {"valueInputOption": "USER_ENTERED",
                "data": [{"range": rng, "values": [[safe_cell(c) for c in row] for row in rows]} for rng, rows in data]}
        r = self.s.post(url, json=body, timeout=60)
        if r.status_code == 403:
            raise SheetAccessError("시트에 쓸 권한이 없습니다. 원본 시트를 서버 서비스 계정에 '편집자'로 공유해 주세요.")
        if r.status_code == 404:
            raise SheetAccessError("시트 또는 탭을 찾을 수 없습니다.")
        r.raise_for_status()
        return int(r.json().get("totalUpdatedCells", 0))
