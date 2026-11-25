"""파일 업로드 → 행(list[dict]) 변환. 형식별 파서를 등록부에 둔다 (새 형식은 등록만).

검증·저장은 하지 않는다 — 변환한 행을 ChangeHandler.preview 에 넘겨 미리보기부터 시작한다.
"""
from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from pathlib import PurePath

from app.core.errors import InvalidInput
from app.core.registry import Registry

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000


class TableParser(ABC):
    @abstractmethod
    def parse(self, data: bytes) -> list[dict]: ...


class CsvParser(TableParser):
    """UTF-8(BOM 허용) 또는 엑셀 한글 CSV(cp949). 머리글 앞뒤 공백 제거, 빈 줄 무시."""

    def parse(self, data: bytes) -> list[dict]:
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise InvalidInput({"file": "글자 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949 CSV 로 저장해 주세요)."})
        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [(h or "").strip() for h in (reader.fieldnames or [])]
        rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]
        return [r for r in rows if any(r.values())]


PARSERS: Registry[TableParser] = Registry("업로드 형식")
PARSERS.register(".csv", CsvParser())


def parse_upload(filename: str, data: bytes) -> list[dict]:
    ext = PurePath(filename or "").suffix.lower()
    if ext not in PARSERS:
        raise InvalidInput({"file": f"지원하는 파일 형식: {', '.join(PARSERS.names())}"})
    if len(data) > MAX_BYTES:
        raise InvalidInput({"file": f"파일은 {MAX_BYTES // 1024 // 1024}MB 이하만 올릴 수 있습니다."})
    rows = PARSERS.get(ext).parse(data)
    if not rows:
        raise InvalidInput({"file": "데이터 행이 없습니다."})
    if len(rows) > MAX_ROWS:
        raise InvalidInput({"file": f"한 번에 {MAX_ROWS:,}행까지 올릴 수 있습니다."})
    return rows
