"""차트 — 외부 라이브러리 없이 서버에서 SVG 를 만든다.

line_chart(): 주차별 추이 같은 작은 꺾은선 차트 (점에 마우스를 올리면 값 표시)
sparkline() : 목록 행에 넣는 아주 작은 추이선
bar_chart() : 0 기준 위(여유)·아래(부족) 막대 — FTE 갭 같은 값
count_bars(): 주차별 건수 막대 + 평균 점선 (기준 주 진하게, 러닝 주 흐리게)
색·글꼴은 static/css/tokens.css 의 CSS 변수를 그대로 쓴다.
"""
from __future__ import annotations

from html import escape


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else (f"{v:,.1f}" if abs(v) >= 10 else f"{v:,.2f}")


def line_chart(labels: list[str], values: list[float | None], *, unit: str = "",
               width: int = 320, height: int = 140, ref: float | None = None, ref_label: str = "") -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if not pts:
        return '<div class="chart-empty">데이터 없음</div>'
    pad_l, pad_r, pad_t, pad_b = 36, 10, 12, 22
    vs = [v for _, v in pts] + ([ref] if ref is not None else [])
    lo, hi = min(vs), max(vs)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    span = hi - lo
    lo, hi = lo - span * 0.1, hi + span * 0.1
    n = max(1, len(values) - 1)
    x = lambda i: pad_l + (width - pad_l - pad_r) * i / n                     # noqa: E731
    y = lambda v: pad_t + (height - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))  # noqa: E731

    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" role="img">']
    for gv in (lo + (hi - lo) * k / 3 for k in range(4)):
        out.append(f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        out.append(f'<text class="axis" x="{pad_l - 4}" y="{y(gv) + 3:.1f}" text-anchor="end">{_fmt(gv)}</text>')
    if ref is not None:
        out.append(f'<line class="ref" x1="{pad_l}" x2="{width - pad_r}" y1="{y(ref):.1f}" y2="{y(ref):.1f}"/>')
        if ref_label:
            out.append(f'<text class="axis ref-label" x="{width - pad_r}" y="{y(ref) - 3:.1f}" text-anchor="end">{escape(ref_label)}</text>')
    step = max(1, len(labels) // 4)
    for i, lab in enumerate(labels):
        if i % step == 0 or i == len(labels) - 1:
            out.append(f'<text class="axis" x="{x(i):.1f}" y="{height - 6}" text-anchor="middle">{escape(lab)}</text>')
    path = " ".join(f"{'M' if k == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for k, (i, v) in enumerate(pts))
    out.append(f'<path class="line" d="{path}"/>')
    for i, v in pts:
        out.append(f'<circle class="dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="3">'
                   f'<title>{escape(labels[i])}: {_fmt(v)}{escape(unit)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def sparkline(values: list[float | None], width: int = 90, height: int = 24) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    hi = hi if hi != lo else lo + 1
    n = len(values) - 1
    d = " ".join(f"{'M' if k == 0 else 'L'}{2 + (width - 4) * i / n:.1f},{2 + (height - 4) * (1 - (v - lo) / (hi - lo)):.1f}"
                 for k, (i, v) in enumerate(pts))
    return f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}"><path d="{d}"/></svg>'


def count_bars(labels: list[str], values: list[float | None], *, avg: float | None = None, mark: int | None = None,
               faded: int | None = None, unit: str = "", width: int = 260, height: int = 110) -> str:
    """주차별 건수 막대. mark 번째 = 비교 기준 주(.bar-mark), faded 번째 = 러닝 주(.bar-faded), 평균은 점선."""
    if not any(v for v in values if v is not None) and not avg:
        return '<div class="chart-empty small">기록 없음</div>'
    pad_l, pad_r, pad_t, pad_b = 24, 6, 10, 18
    hi = max([v for v in values if v is not None] + [avg or 0, 1]) * 1.15
    y = lambda v: pad_t + (height - pad_t - pad_b) * (1 - v / hi)  # noqa: E731
    n = max(1, len(values))
    slot = (width - pad_l - pad_r) / n
    bw = max(2.0, slot * 0.62)
    out = [f'<svg class="chart cbars" viewBox="0 0 {width} {height}" width="100%" role="img">']
    for gv in (0, hi / 2):
        out.append(f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        out.append(f'<text class="axis" x="{pad_l - 4}" y="{y(gv) + 3:.1f}" text-anchor="end">{gv:,.0f}</text>')
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = pad_l + slot * (i + 0.5)
        if v is not None:
            cls = "cbar" + (" bar-mark" if i == mark else "") + (" bar-faded" if i == faded else "")
            top = y(v)
            out.append(f'<rect class="{cls}" x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(y(0) - top, 0.5):.1f}">'
                       f'<title>{escape(lab)}: {v:,.0f}{escape(unit)}</title></rect>')
        if i == 0 or i == mark or (i == n - 1 and (mark is None or n - 1 - mark > 1)):   # 기준 주 옆 마지막 라벨은 겹쳐서 뺌
            out.append(f'<text class="axis" x="{cx:.1f}" y="{height - 5}" text-anchor="middle">{escape(lab)}</text>')
    if avg is not None:
        out.append(f'<line class="ref" x1="{pad_l}" x2="{width - pad_r}" y1="{y(avg):.1f}" y2="{y(avg):.1f}">'
                   f'<title>평균 {avg:,.1f}{escape(unit)}</title></line>')
    out.append("</svg>")
    return "".join(out)


def bar_chart(labels: list[str], values: list[float | None], *, unit: str = "",
              width: int = 640, height: int = 160, mark: str | None = None) -> str:
    """0 기준 막대. 양수 = .bar-pos, 음수 = .bar-neg. mark 라벨의 막대는 .bar-mark 로 강조(예: 이번 주)."""
    if not any(v is not None for v in values):
        return '<div class="chart-empty">데이터 없음</div>'
    pad_l, pad_r, pad_t, pad_b = 36, 10, 12, 22
    vs = [v for v in values if v is not None] + [0.0]
    lo, hi = min(vs), max(vs)
    if hi == lo:
        hi += 1
    span = hi - lo
    lo, hi = (lo - span * 0.1 if lo < 0 else 0), (hi + span * 0.1 if hi > 0 else 0)
    y = lambda v: pad_t + (height - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))  # noqa: E731
    n = max(1, len(values))
    slot = (width - pad_l - pad_r) / n
    bw = max(2.0, slot * 0.7)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" role="img">']
    for gv in (lo + (hi - lo) * k / 3 for k in range(4)):
        out.append(f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y(gv):.1f}" y2="{y(gv):.1f}"/>')
        out.append(f'<text class="axis" x="{pad_l - 4}" y="{y(gv) + 3:.1f}" text-anchor="end">{_fmt(gv)}</text>')
    out.append(f'<line class="zero" x1="{pad_l}" x2="{width - pad_r}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    step = max(1, n // 6)
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = pad_l + slot * (i + 0.5)
        if v is not None:
            top, bot = sorted((y(v), y(0)))
            cls = "bar-pos" if v >= 0 else "bar-neg"
            if lab == mark:
                cls += " bar-mark"
            out.append(f'<rect class="{cls}" x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 1):.1f}">'
                       f'<title>{escape(lab)}: {v:+,.1f}{escape(unit)}</title></rect>')
        if i % step == 0 or i == n - 1:
            out.append(f'<text class="axis" x="{cx:.1f}" y="{height - 6}" text-anchor="middle">{escape(lab)}</text>')
    out.append("</svg>")
    return "".join(out)
