"""Inline-SVG charts shared by the dashboard, round reports and the public site.

Marks are styled by CSS roles (see VIZ_CSS), so light/dark themes swap in one place.
Follows the dataviz method: one hue for a single series, 2px lines, >=8px dots with a 2px
surface ring, hairline solid grid, text in text tokens, a sequential one-hue ramp for the
heatmap, <title> tooltips on every mark, and a table view next to each chart.
"""

from __future__ import annotations

import html

SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281"]

VIZ_CSS = """
.viz{--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--grid:#e6e5e1;--series-1:#2a78d6;--band:#2a78d61f}
@media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])) .viz{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#34332f;--series-1:#3987e5;--band:#3987e526}}
:root[data-theme="dark"] .viz{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#34332f;--series-1:#3987e5;--band:#3987e526}
.viz svg{display:block;width:100%;height:auto;overflow:visible}.viz text{font:12px system-ui,sans-serif;fill:var(--text-secondary);font-variant-numeric:tabular-nums}
.viz .lbl{fill:var(--text-primary);font-weight:600}.viz .grid{stroke:var(--grid);stroke-width:1}.viz .whisker{stroke:var(--series-1);stroke-width:2;stroke-linecap:round}
.viz .dot{fill:var(--series-1);stroke:var(--surface-1);stroke-width:2}.viz .tied{fill:var(--band)}.viz .hit{fill:transparent}.viz .hit:hover + .dot,.viz g:hover .dot{r:7}
"""


def _x(v: float, lo: float, hi: float, x0: float, w: float) -> float:
    return x0 + (v - lo) / (hi - lo) * w


def ci_chart(rows: list[dict], lo: float = 1, hi: float = 7, width: int = 640, label_w: int = 190, title: str = "Overall score with 95% CI") -> str:
    """rows: [{label, mean, lo, hi, note?}] sorted best-first."""
    row_h, top, bottom = 34, 28, 30
    h = top + row_h * len(rows) + bottom
    x0, w = label_w, width - label_w - 24
    parts = [f'<svg viewBox="0 0 {width} {h}" style="max-width:{width}px" role="img" aria-label="{html.escape(title)}">']
    for t in range(int(lo), int(hi) + 1):
        x = _x(t, lo, hi, x0, w)
        parts.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 8}" y2="{h - bottom + 4}"/><text x="{x:.1f}" y="{h - 10}" text-anchor="middle">{t}</text>')
    # shade the best model's interval: anyone overlapping it is statistically tied for first
    if rows and rows[0].get("lo") is not None:
        a, b = _x(rows[0]["lo"], lo, hi, x0, w), _x(rows[0]["hi"], lo, hi, x0, w)
        parts.append(f'<rect class="tied" x="{a:.1f}" y="{top - 8}" width="{max(b - a, 1):.1f}" height="{row_h * len(rows) + 4}" rx="4"><title>Range of the top model\'s 95% CI</title></rect>')
    for i, r in enumerate(rows):
        y = top + row_h * i + row_h / 2
        parts.append(f'<text class="lbl" x="{label_w - 12}" y="{y + 4:.1f}" text-anchor="end">{html.escape(r["label"])}</text>')
        if r.get("mean") is None:
            parts.append(f'<text x="{x0 + 6}" y="{y + 4:.1f}">no scores yet</text>')
            continue
        m = _x(r["mean"], lo, hi, x0, w)
        tip = f'{r["label"]}: {r["mean"]:.2f}' + (f' (95% CI {r["lo"]:.2f}–{r["hi"]:.2f})' if r.get("lo") is not None else "") + (f' · {r["note"]}' if r.get("note") else "")
        parts.append(f"<g><title>{html.escape(tip)}</title>")
        if r.get("lo") is not None:
            a, b = _x(r["lo"], lo, hi, x0, w), _x(r["hi"], lo, hi, x0, w)
            parts.append(f'<line class="whisker" x1="{a:.1f}" x2="{b:.1f}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<rect class="hit" x="{x0}" y="{y - row_h / 2:.1f}" width="{w}" height="{row_h}"/><circle class="dot" cx="{m:.1f}" cy="{y:.1f}" r="5"/></g>')
        parts.append(f'<text x="{min(m + 10, x0 + w - 4):.1f}" y="{y - 9:.1f}">{r["mean"]:.2f}</text>')
    parts.append("</svg>")
    return f'<figure class="viz" style="margin:0">{"".join(parts)}<figcaption class="small muted">{html.escape(title)}. Shaded band: the top model\'s 95% interval; models whose whiskers reach it are statistically tied.</figcaption></figure>'


def heat_cell(v: float | None, lo: float = 1, hi: float = 7) -> str:
    """Inline style for a heatmap <td> on the sequential blue ramp, with readable text."""
    if v is None:
        return ""
    i = round((v - lo) / (hi - lo) * (len(SEQ) - 1))
    i = max(0, min(len(SEQ) - 1, i))
    ink = "#ffffff" if i >= 7 else "#0b0b0b"
    return f"background:{SEQ[i]};color:{ink}"


def scatter(points: list[dict], width: int = 560, height: int = 300, x_label: str = "Mean cost per run (USD)", y_label: str = "Overall score") -> str:
    """points: [{label, x, y}] single series; labels drawn beside each dot (few points)."""
    pts = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not pts:
        return '<p class="small muted">No cost data yet (mock models cost $0).</p>'
    x0, y0, w, h = 56, 16, width - 80, height - 56
    xmax = max(p["x"] for p in pts) * 1.15 or 1
    parts = [f'<svg viewBox="0 0 {width} {height}" style="max-width:{width}px" role="img" aria-label="{html.escape(y_label)} vs {html.escape(x_label)}">']
    for t in range(1, 8):
        y = y0 + h - (t - 1) / 6 * h
        parts.append(f'<line class="grid" x1="{x0}" x2="{x0 + w}" y1="{y:.1f}" y2="{y:.1f}"/><text x="{x0 - 8}" y="{y + 4:.1f}" text-anchor="end">{t}</text>')
    for k in range(5):
        v = xmax * k / 4
        x = x0 + v / xmax * w
        parts.append(f'<text x="{x:.1f}" y="{y0 + h + 18}" text-anchor="middle">${v:,.2f}</text>')
    for p in pts:
        x = x0 + p["x"] / xmax * w
        y = y0 + h - (p["y"] - 1) / 6 * h
        parts.append(f'<g><title>{html.escape(p["label"])}: {p["y"]:.2f} at ${p["x"]:,.2f}</title><circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="5"/></g>'
                     f'<text class="lbl" x="{x + 9:.1f}" y="{y + 4:.1f}">{html.escape(p["label"])}</text>')
    parts.append(f'<text x="{x0 + w / 2}" y="{height - 4}" text-anchor="middle">{html.escape(x_label)}</text></svg>')
    return f'<figure class="viz" style="margin:0">{"".join(parts)}</figure>'
