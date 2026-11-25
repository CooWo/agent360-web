"""파일 업로드 → 행(list[dict]) 변환. 형식별 파서를 등록부에 둔다 (새 형식은 등록만).

검증·저장은 하지 않는다 — 변환한 행을 ChangeHandler.preview 에 넘겨 미리보기부터 시작한다.
"""
from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from datetime import date, datetime
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


class GridReader(ABC):
    """파일 → 칸 격자(list[list[str]]). 머리글 줄 찾기는 쓰는 쪽에서 (시트처럼 머리글 위에 줄이 더 있을 수 있음)."""

    @abstractmethod
    def grid(self, data: bytes) -> list[list[str]]: ...


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InvalidInput({"file": "글자 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949 로 저장해 주세요)."})


def text_grid(text: str, delimiter: str = "\t") -> list[list[str]]:
    """구분 글자 표 → 격자. 시트에서 복사한 글(탭 구분, 줄바꿈 있는 칸은 따옴표)도 이걸로 읽는다."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delimiter)]


class DelimitedGrid(GridReader):
    def __init__(self, delimiter: str):
        self.delimiter = delimiter

    def grid(self, data: bytes) -> list[list[str]]:
        return text_grid(_decode(data), self.delimiter)


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


class XlsxGrid(GridReader):
    """엑셀(.xlsx) 첫 시트 (또는 이름이 맞는 시트). 날짜 칸은 YYYY-MM-DD 로."""

    def __init__(self, prefer_sheet: str = ""):
        self.prefer_sheet = prefer_sheet

    def grid(self, data: bytes) -> list[list[str]]:
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise InvalidInput({"file": "엑셀 파일을 열 수 없습니다 (.xlsx 로 저장했는지 확인해 주세요)."}) from None
        try:
            ws = wb[self.prefer_sheet] if self.prefer_sheet in wb.sheetnames else wb.worksheets[0]
            out = []
            for n, row in enumerate(ws.iter_rows(values_only=True)):
                if n >= MAX_ROWS + 10:
                    raise InvalidInput({"file": f"한 번에 {MAX_ROWS:,}행까지 올릴 수 있습니다."})
                out.append([_cell_text(v) for v in row])
            return out
        finally:
            wb.close()


GRIDS: Registry[GridReader] = Registry("표 파일 형식")
GRIDS.register(".csv", DelimitedGrid(","))
GRIDS.register(".tsv", DelimitedGrid("\t"))
GRIDS.register(".txt", DelimitedGrid("\t"))
GRIDS.register(".xlsx", XlsxGrid())


def parse_grid(filename: str, data: bytes) -> list[list[str]]:
    """파일 → 격자 (빈 줄 제거 안 함 — 줄 번호를 지키려고)."""
    ext = PurePath(filename or "").suffix.lower()
    if ext not in GRIDS:
        raise InvalidInput({"file": f"지원하는 파일 형식: {', '.join(GRIDS.names())}"})
    if len(data) > MAX_BYTES:
        raise InvalidInput({"file": f"파일은 {MAX_BYTES // 1024 // 1024}MB 이하만 올릴 수 있습니다."})
    if not data:
        raise InvalidInput({"file": "빈 파일입니다."})
    return GRIDS.get(ext).grid(data)


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
