"""Statistical engine: tests per metric type, CIs, CUPED, power, corrections, segments."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

from .schemas import (
    ExperimentConfig, MetricResult, MetricSpec, PowerResult, SegmentReport, SegmentResult,
)


# --------------------------------------------------------------------- estimators
def _group_estimate(y: np.ndarray, kind: str, den: np.ndarray | None = None):
    """Return (estimate, standard error of the estimate) for one arm."""
    n = len(y)
    if kind == "proportion":
        m = y.mean()
        return m, np.sqrt(m * (1 - m) / n)
    if kind == "mean":
        return y.mean(), y.std(ddof=1) / np.sqrt(n)
    # ratio of sums via the delta method
    r = y.sum() / den.sum()
    resid = y - r * den
    return r, resid.std(ddof=1) / (np.sqrt(n) * den.mean())


def _inference(m_c, se_c, n_c, m_t, se_t, n_t, alpha, welch):
    diff = m_t - m_c
    se = float(np.hypot(se_c, se_t))
    if se == 0:
        return diff, 0.0, diff, diff, 1.0
    if welch:
        df = se**4 / (se_c**4 / (n_c - 1) + se_t**4 / (n_t - 1))
        crit = stats.t.ppf(1 - alpha / 2, df)
        p = 2 * stats.t.sf(abs(diff / se), df)
    else:
        crit = stats.norm.ppf(1 - alpha / 2)
        p = 2 * stats.norm.sf(abs(diff / se))
    return diff, se, diff - crit * se, diff + crit * se, float(p)


def cuped_adjust(y: np.ndarray, x: np.ndarray):
    """CUPED: y' = y - theta * (x - mean(x)), theta estimated on pooled data."""
    theta = np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1)
    y_adj = y - theta * (x - x.mean())
    vr = 1 - np.var(y_adj, ddof=1) / np.var(y, ddof=1)
    return y_adj, float(theta), float(vr)


def analyze_metric(df: pd.DataFrame, cfg: ExperimentConfig, spec: MetricSpec,
                   variant: str, use_cuped: bool = True) -> MetricResult:
    vc = cfg.variant_col
    sub = df[df[vc].isin([cfg.control_label, variant])]
    cols = [spec.column] + ([spec.denominator] if spec.kind == "ratio" else [])
    sub = sub.dropna(subset=cols)
    is_c = (sub[vc] == cfg.control_label).to_numpy()
    y = sub[spec.column].to_numpy(float)
    den = sub[spec.denominator].to_numpy(float) if spec.kind == "ratio" else None
    n_c, n_t = int(is_c.sum()), int((~is_c).sum())
    if min(n_c, n_t) < 2:
        raise ValueError(f"Not enough users in '{variant}' or control for {spec.column}")

    m_c, se_c = _group_estimate(y[is_c], spec.kind, None if den is None else den[is_c])
    m_t, se_t = _group_estimate(y[~is_c], spec.kind, None if den is None else den[~is_c])
    sd_c, sd_t = se_c * np.sqrt(n_c), se_t * np.sqrt(n_t)

    est = (m_c, se_c, m_t, se_t)
    welch = spec.kind == "mean"
    test = {"proportion": "two-proportion z-test", "mean": "Welch t-test",
            "ratio": "delta-method z-test (ratio of sums)"}[spec.kind]
    cuped_used, vr = False, None

    if use_cuped and spec.use_cuped and cfg.covariate_col and spec.kind in ("proportion", "mean"):
        x = pd.to_numeric(sub[cfg.covariate_col], errors="coerce")
        x = x.fillna(x.mean()).to_numpy(float)
        if np.isfinite(x).all() and x.std() > 0 and y.std() > 0:
            y_adj, _, vr = cuped_adjust(y, x)
            if vr >= 0.01:
                a_c, a_se_c = _group_estimate(y_adj[is_c], "mean")
                a_t, a_se_t = _group_estimate(y_adj[~is_c], "mean")
                est, welch, cuped_used = (a_c, a_se_c, a_t, a_se_t), True, True
                test = "Welch t-test on CUPED-adjusted values"

    diff, se, lo, hi, p = _inference(est[0], est[1], n_c, est[2], est[3], n_t, cfg.alpha, welch)

    if spec.kind == "proportion":
        es, es_name = 2 * np.arcsin(np.sqrt(m_t)) - 2 * np.arcsin(np.sqrt(m_c)), "Cohen's h"
    elif spec.kind == "mean":
        pooled = np.sqrt(((n_c - 1) * sd_c**2 + (n_t - 1) * sd_t**2) / (n_c + n_t - 2))
        es, es_name = ((m_t - m_c) / pooled if pooled > 0 else 0.0), "Cohen's d"
    else:
        es, es_name = None, None

    rel = rel_lo = rel_hi = None
    if m_c > 0:
        rel, rel_lo, rel_hi = diff / m_c, lo / m_c, hi / m_c

    return MetricResult(
        metric=spec.column, kind=spec.kind, variant=variant, direction=spec.direction,
        n_control=n_c, n_treatment=n_t, control_value=float(m_c), treatment_value=float(m_t),
        abs_diff=float(diff), se_diff=float(se), ci_low=float(lo), ci_high=float(hi),
        rel_lift=rel, ci_rel_low=rel_lo, ci_rel_high=rel_hi, p_value=p,
        effect_size=None if es is None else float(es), effect_size_name=es_name, test=test,
        cuped_used=cuped_used, variance_reduction=vr, control_sd=float(sd_c),
    )


def is_good(r: MetricResult) -> bool:
    """True if the observed movement is in the desired direction."""
    return (r.abs_diff > 0) == (r.direction == "higher_better")


# ----------------------------------------------------------------- multiple testing
def apply_correction(results: list[MetricResult], method: str, alpha: float) -> None:
    """Adjust p-values across every (variant x metric) comparison, in place."""
    if not results:
        return
    adj = multipletests([r.p_value for r in results], alpha=alpha, method=method)[1]
    for r, p in zip(results, adj):
        r.p_adjusted = float(p)


# ------------------------------------------------------------------------- power
def required_n_per_arm(baseline: float, mde_rel: float, alpha: float, power: float,
                       kind: str, sd: float | None = None, vr: float = 0.0) -> int:
    if kind == "proportion":
        p2 = min(baseline * (1 + mde_rel), 0.999)
        eff = abs(proportion_effectsize(p2, baseline))
    else:
        eff = abs(baseline * mde_rel) / sd
    if eff == 0:
        return 10**9
    n = NormalIndPower().solve_power(effect_size=eff, alpha=alpha, power=power, ratio=1.0)
    return int(np.ceil(n * (1 - max(vr, 0.0))))


def achievable_mde_rel(baseline: float, n_per_arm: int, alpha: float, power: float,
                       kind: str, sd: float | None = None, vr: float = 0.0) -> float:
    n_eff = n_per_arm / (1 - max(vr, 0.0))
    eff = NormalIndPower().solve_power(effect_size=None, nobs1=n_eff, alpha=alpha,
                                       power=power, ratio=1.0)
    if kind == "proportion":
        angle = min(np.arcsin(np.sqrt(baseline)) + eff / 2, np.pi / 2)
        return float((np.sin(angle) ** 2 - baseline) / baseline)
    return float(eff * sd / abs(baseline))


def power_summary(prim: MetricResult, cfg: ExperimentConfig, n_days: int | None) -> PowerResult:
    n_arm = min(prim.n_control, prim.n_treatment)
    vr = prim.variance_reduction if prim.cuped_used and prim.variance_reduction else 0.0
    base = prim.control_value
    req = required_n_per_arm(base, cfg.mde_rel, cfg.alpha, cfg.power, prim.kind, prim.control_sd, vr)
    mde = achievable_mde_rel(base, n_arm, cfg.alpha, cfg.power, prim.kind, prim.control_sd, vr)
    extra = None
    if n_days and n_arm < req:
        extra = float((req - n_arm) / (n_arm / n_days))
    return PowerResult(baseline=base, n_per_arm=n_arm, target_mde_rel=cfg.mde_rel,
                       required_n_per_arm=req, achievable_mde_rel=mde,
                       powered=n_arm >= req, extra_days_needed=extra)


# ---------------------------------------------------------------------- segments
def segment_analysis(df: pd.DataFrame, cfg: ExperimentConfig, spec: MetricSpec, variant: str,
                     max_levels: int = 8, min_n: int = 200) -> SegmentReport | None:
    rows: list[SegmentResult] = []
    het: dict[str, float] = {}
    sub_all = df[df[cfg.variant_col].isin([cfg.control_label, variant])]
    for col in cfg.segment_cols:
        col_rows = []
        for level in sub_all[col].value_counts().head(max_levels).index:
            seg = sub_all[sub_all[col] == level]
            counts = seg[cfg.variant_col].value_counts()
            if min(counts.get(cfg.control_label, 0), counts.get(variant, 0)) < min_n:
                continue
            r = analyze_metric(seg, cfg, spec, variant, use_cuped=False)
            col_rows.append(SegmentResult(
                segment_col=col, level=str(level), n_control=r.n_control, n_treatment=r.n_treatment,
                abs_diff=r.abs_diff, se_diff=r.se_diff, rel_lift=r.rel_lift,
                ci_low=r.ci_low, ci_high=r.ci_high, p_value=r.p_value))
        if len(col_rows) >= 2:  # Cochran's Q: do effects differ across levels at all?
            d = np.array([r.abs_diff for r in col_rows])
            w = 1 / np.array([max(r.se_diff, 1e-12) for r in col_rows]) ** 2
            q = float((w * (d - (w * d).sum() / w.sum()) ** 2).sum())
            het[col] = float(stats.chi2.sf(q, len(col_rows) - 1))
        rows += col_rows
    if not rows:
        return None
    adj = multipletests([r.p_value for r in rows], alpha=cfg.alpha, method=cfg.correction)[1]
    for r, p in zip(rows, adj):
        r.p_adjusted = float(p)
    k = len(rows)
    raw_sig = sum(r.p_value < cfg.alpha for r in rows)
    adj_sig = sum(r.p_adjusted < cfg.alpha for r in rows)
    fw = 1 - (1 - cfg.alpha) ** k
    heterogeneous = [c for c, p in het.items() if p < cfg.alpha]
    warning = (f"{k} segment cuts were tested, so the chance of at least one false positive is "
               f"about {fw * 100:.0f}% even if nothing is going on. "
               f"{raw_sig} segment(s) look significant before correction and {adj_sig} after correction. ")
    warning += ("Effects differ across levels of: " + ", ".join(heterogeneous) +
                " (heterogeneity test). Treat as hypotheses to confirm in a follow-up test."
                if heterogeneous else
                "No heterogeneity test is significant, so differences between segments are "
                "consistent with noise. Do not ship or kill for one segment based on this view.")
    return SegmentReport(results=rows, heterogeneity_p=het, n_tested=k,
                         familywise_false_positive_risk=float(fw), n_significant_raw=raw_sig,
                         n_significant_adjusted=adj_sig, warning=warning)