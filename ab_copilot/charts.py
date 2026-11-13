"""Plotly figures for the dashboard."""
from __future__ import annotations

import plotly.graph_objects as go

from .schemas import CheckResult, MetricResult, SegmentReport


def fig_srm(check: CheckResult) -> go.Figure:
    d = check.details
    fig = go.Figure([go.Bar(name="Expected", x=d["labels"], y=d["expected"]),
                     go.Bar(name="Observed", x=d["labels"], y=d["observed"])])
    fig.update_layout(barmode="group", title="Users per variant: expected vs observed", height=320)
    return fig


def fig_cumulative_p(ts, alpha: float) -> go.Figure:
    fig = go.Figure(go.Scatter(x=ts.index, y=ts["cum_p"], mode="lines+markers", name="cumulative p-value"))
    fig.add_hline(y=alpha, line_dash="dash", line_color="red", annotation_text=f"alpha = {alpha}")
    fig.update_layout(title="Cumulative p-value by day (what you would see if you peeked daily)",
                      yaxis_title="p-value", yaxis_range=[0, 1], height=340)
    return fig


def fig_daily_lift(ts, kind: str) -> go.Figure:
    scale = 100 if kind == "proportion" else 1
    unit = "pp" if kind == "proportion" else ""
    fig = go.Figure(go.Scatter(x=ts.index, y=ts["daily_diff"] * scale, mode="lines+markers",
                               error_y=dict(type="data", array=1.96 * ts["daily_se"] * scale),
                               name="daily difference"))
    fig.add_hline(y=0, line_dash="dot")
    fig.update_layout(title="Daily treatment - control difference (95% bars): fading = novelty",
                      yaxis_title=f"difference {unit}".strip(), height=340)
    return fig


def fig_forest(results: list[MetricResult]) -> go.Figure:
    rows = [r for r in results if r.rel_lift is not None]
    fig = go.Figure(go.Scatter(
        x=[r.rel_lift * 100 for r in rows], y=[f"{r.metric} ({r.variant})" for r in rows], mode="markers",
        error_x=dict(type="data", symmetric=False,
                     array=[(r.ci_rel_high - r.rel_lift) * 100 for r in rows],
                     arrayminus=[(r.rel_lift - r.ci_rel_low) * 100 for r in rows])))
    fig.add_vline(x=0, line_dash="dot")
    fig.update_layout(title="Relative lift with confidence interval (%)", height=120 + 60 * len(rows))
    return fig


def fig_segments(report: SegmentReport, kind: str) -> go.Figure:
    s = 100 if kind == "proportion" else 1
    rows = report.results
    fig = go.Figure(go.Scatter(
        x=[r.abs_diff * s for r in rows], y=[f"{r.segment_col}={r.level}" for r in rows], mode="markers",
        marker=dict(color=["crimson" if (r.p_adjusted or 1) < 0.05 else "gray" for r in rows]),
        error_x=dict(type="data", symmetric=False, array=[(r.ci_high - r.abs_diff) * s for r in rows],
                     arrayminus=[(r.abs_diff - r.ci_low) * s for r in rows])))
    fig.add_vline(x=0, line_dash="dot")
    fig.update_layout(title="Effect by segment (red = significant after correction)",
                      xaxis_title="difference (pp for proportions)", height=120 + 36 * len(rows))
    return fig