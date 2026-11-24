"""차트 — 외부 라이브러리 없이 서버에서 SVG 를 만든다.

line_chart(): 주차별 추이 같은 작은 꺾은선 차트 (점에 마우스를 올리면 값 표시)
sparkline() : 목록 행에 넣는 아주 작은 추이선
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
