"""End-to-end orchestration: prep -> health -> stats -> decision."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .decision import decide
from .health import build_timeseries, check_novelty, check_peeking, check_srm
from .prep import prepare
from .schemas import (
    CheckResult, Decision, ExperimentConfig, MetricResult, PowerResult, SegmentReport,
)
from .stats import analyze_metric, apply_correction, power_summary, segment_analysis


@dataclass
class VariantReport:
    variant: str
    primary: MetricResult
    guardrails: list[MetricResult]
    secondary: list[MetricResult]
    checks: list[CheckResult]  # variant-specific (peeking, novelty)
    power: PowerResult
    segments: Optional[SegmentReport]
    timeseries: Optional[pd.DataFrame]
    decision: Optional[Decision] = None


@dataclass
class AnalysisBundle:
    cfg: ExperimentConfig
    df: pd.DataFrame
    global_checks: list[CheckResult]
    variants: dict[str, VariantReport] = field(default_factory=dict)
    n_raw_rows: int = 0
    n_days: Optional[int] = None

    def all_checks(self, variant: str) -> list[CheckResult]:
        return [*self.global_checks, *self.variants[variant].checks]


def run_analysis(raw: pd.DataFrame, cfg: ExperimentConfig) -> AnalysisBundle:
    df, dq = prepare(raw, cfg)
    bundle = AnalysisBundle(cfg=cfg, df=df, global_checks=[check_srm(df, cfg), *dq], n_raw_rows=len(raw))
    if cfg.time_col and df[cfg.time_col].notna().any():
        span = df[cfg.time_col].max() - df[cfg.time_col].min()
        bundle.n_days = max(int(span.days) + 1, 1)

    everything: list[MetricResult] = []
    for v in cfg.treatment_labels:
        prim = analyze_metric(df, cfg, cfg.primary, v)
        guards = [analyze_metric(df, cfg, g, v) for g in cfg.guardrails]
        secs = [analyze_metric(df, cfg, m, v) for m in cfg.secondary]
        ts = build_timeseries(df, cfg, v, cfg.primary)
        power = power_summary(prim, cfg, bundle.n_days)
        checks = [check_peeking(ts, power.n_per_arm, cfg), check_novelty(ts, cfg.primary.kind)]
        segs = segment_analysis(df, cfg, cfg.primary, v) if cfg.segment_cols else None
        bundle.variants[v] = VariantReport(v, prim, guards, secs, checks, power, segs, ts)
        everything += [prim, *secs]  # guardrails are not corrected: missing a harm costs more

    apply_correction(everything, cfg.correction, cfg.alpha)
    for r in bundle.variants.values():
        r.decision = decide(r.primary, r.guardrails, bundle.all_checks(r.variant), r.power, cfg)
    return bundle