"""AI 답변 → 안전한 HTML. 외부 라이브러리 없이 필요한 마크다운만 처리한다.

모든 글자는 먼저 escape 하고, 그 다음에 굵게·코드·제목·목록·표만 태그로 바꾼다 (AI 답변에 든 HTML 은 실행되지 않음).
"""
from __future__ import annotations

import html
import re

from app.core.ai.data_agent import Answer


def _inline(s: str) -> str:
    s = html.escape(s, quote=True)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>").replace("&lt;br /&gt;", "<br>")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _num_class(v: str) -> str:
    return ' class="num"' if re.fullmatch(r"[-+]?[\d,]*\.?\d+%?", v.strip() or "x") else ""


def md_to_html(text: str) -> str:
    out: list[str] = []
    lines = text.replace("\r\n", "\n").split("\n")
    i, para, lst = 0, [], None

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    def close_list():
        nonlocal lst
        if lst:
            out.append(f"</{lst}>")
            lst = None

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("|"):                                   # 마크다운 표
            flush_para(); close_list()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i]); i += 1
            rows = [_cells(b) for b in block if not re.match(r"^\s*\|?\s*:?-{2,}", b)]
            if rows:
                head, body = rows[0], rows[1:]
                out.append('<div class="tbl-wrap"><table class="tbl"><thead><tr>'
                           + "".join(f"<th>{_inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
                           + "".join("<tr>" + "".join(f"<td{_num_class(c)}>{_inline(c)}</td>" for c in r) + "</tr>"
                                     for r in body)
                           + "</tbody></table></div>")
            continue
        m_h = re.match(r"^(#{1,6})\s+(.*)", s)
        m_ul = re.match(r"^[-*•]\s+(.*)", s)
        m_ol = re.match(r"^\d+[.)]\s+(.*)", s)
        if not s:
            flush_para(); close_list()
        elif m_h:
            flush_para(); close_list()
            out.append(f"<h4>{_inline(m_h.group(2))}</h4>")
        elif m_ul or m_ol:
            flush_para()
            kind = "ul" if m_ul else "ol"
            if lst != kind:
                close_list(); out.append(f"<{kind}>"); lst = kind
            out.append(f"<li>{_inline((m_ul or m_ol).group(1))}</li>")
        else:
            close_list()
            para.append(s)
        i += 1
    flush_para(); close_list()
    return "\n".join(out)


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def table_html(seg: dict) -> str:
    head = "".join(f"<th>{html.escape(str(f))}</th>" for f in seg["fields"])
    body = "".join(
        "<tr>" + "".join(f"<td{_num_class(_cell(r.get(f)))}>{html.escape(_cell(r.get(f)))}</td>" for f in seg["fields"]) + "</tr>"
        for r in seg["rows"])
    more = f'<div class="muted small">앞 {len(seg["rows"])}행만 표시</div>' if seg.get("truncated") else ""
    return f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{more}'


def answer_html(ans: Answer) -> str:
    parts = []
    for seg in ans.segments:
        parts.append(md_to_html(seg["text"]) if seg["type"] == "text" else table_html(seg))
    if not parts:
        parts.append('<p class="muted">(답변이 비어 있습니다)</p>')
    return "\n".join(parts)
