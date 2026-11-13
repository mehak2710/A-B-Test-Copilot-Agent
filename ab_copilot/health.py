"""Experiment health checks: SRM, peeking, novelty / primacy."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from .schemas import CheckResult, ExperimentConfig, MetricSpec
from .utils import fmt_diff

# Armitage et al. (1969): overall false-positive rate at alpha=0.05 if you test after
# each of k equally spaced looks and stop at the first significant one.
_PEEK_FPR = {1: .05, 2: .083, 3: .107, 4: .126, 5: .142, 10: .193, 20: .248, 50: .32, 100: .374}


def peeking_fpr(k: int) -> float:
    ks = sorted(_PEEK_FPR)
    return float(np.interp(np.log(max(k, 1)), np.log(ks), [_PEEK_FPR[x] for x in ks]))


# -------------------------------------------------------------------------- SRM
def check_srm(df: pd.DataFrame, cfg: ExperimentConfig) -> CheckResult:
    labels = [cfg.control_label, *cfg.treatment_labels]
    obs = np.array([(df[cfg.variant_col] == l).sum() for l in labels], float)
    split = cfg.expected_split or {l: 1.0 for l in labels}
    share = np.array([split.get(l, 0.0) for l in labels], float)
    share = share / share.sum()
    exp = share * obs.sum()
    chi2, p = stats.chisquare(obs, exp)
    status = "fail" if p < 0.001 else "warn" if p < 0.01 else "pass"
    obs_txt = ", ".join(f"{l}: {int(o):,} ({o / obs.sum() * 100:.2f}%)" for l, o in zip(labels, obs))
    exp_txt = ", ".join(f"{s * 100:.1f}%" for s in share)
    msg = f"Observed {obs_txt}; intended split {exp_txt}. Chi-square p-value {p:.4g}."
    if status != "pass":
        msg += " The groups were not assigned as intended, so any difference between them may be an artifact."
    return CheckResult(name="Sample ratio mismatch (SRM)", status=status, summary=msg,
                       details={"labels": labels, "observed": obs.tolist(),
                                "expected": exp.tolist(), "p_value": float(p)})


# ------------------------------------------------------------------- time series
def build_timeseries(df: pd.DataFrame, cfg: ExperimentConfig, variant: str,
                     spec: MetricSpec) -> Optional[pd.DataFrame]:
    """Daily + cumulative treatment-vs-control difference for proportion / mean metrics."""
    if not cfg.time_col or spec.kind == "ratio":
        return None
    sub = df[df[cfg.variant_col].isin([cfg.control_label, variant])].dropna(
        subset=[cfg.time_col, spec.column])
    if sub.empty:
        return None
    y = sub[spec.column].astype(float)
    tmp = pd.DataFrame({
        "day": sub[cfg.time_col].dt.floor("D"),
        "arm": np.where(sub[cfg.variant_col] == cfg.control_label, "c", "t"),
        "y": y, "y2": y**2})
    g = tmp.groupby(["day", "arm"]).agg(n=("y", "size"), s=("y", "sum"), ss=("y2", "sum")).unstack("arm")
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    g = g.reindex(columns=[f"{a}_{b}" for a in ("n", "s", "ss") for b in ("c", "t")], fill_value=0).fillna(0)
    g = g.sort_index()

    def mean_se(n, s, ss):
        n = n.where(n > 1)
        m = s / n
        var = ((ss - n * m**2) / (n - 1)).clip(lower=0)
        return m, var / n

    out = pd.DataFrame(index=g.index)
    m_c, v_c = mean_se(g["n_c"], g["s_c"], g["ss_c"])
    m_t, v_t = mean_se(g["n_t"], g["s_t"], g["ss_t"])
    out["daily_diff"], out["daily_se"] = m_t - m_c, np.sqrt(v_c + v_t)
    c = g.cumsum()
    cm_c, cv_c = mean_se(c["n_c"], c["s_c"], c["ss_c"])
    cm_t, cv_t = mean_se(c["n_t"], c["s_t"], c["ss_t"])
    se = np.sqrt(cv_c + cv_t).replace(0, np.nan)
    out["cum_diff"] = cm_t - cm_c
    out["cum_p"] = 2 * stats.norm.sf(np.abs(out["cum_diff"] / se))
    out["day_idx"] = np.arange(len(out))
    return out


# ------------------------------------------------------------------------ peeking
def check_peeking(ts: Optional[pd.DataFrame], n_per_arm: int, cfg: ExperimentConfig) -> CheckResult:
    name = "Peeking / early stopping"
    if ts is None or len(ts) < 5:
        return CheckResult(name=name, status="skipped",
                           summary="Needs a timestamp column and at least 5 days of data.")
    p = ts["cum_p"].to_numpy()
    n_days, start = len(p), 2  # ignore the first two days: tiny samples
    sig = np.nan_to_num(p, nan=1.0) < cfg.alpha
    ev = sig[start:]
    first = int(np.argmax(ev)) + start if ev.any() else None
    flips = int(np.sum(ev[1:] != ev[:-1]))
    flags = []
    if sig[-1] and first is not None and first > start and n_days - 1 - first <= 1:
        flags.append(f"the test ends within a day of the p-value first dropping below {cfg.alpha} "
                     f"(day {first + 1} of {n_days}), which is the typical signature of stopping at the first significant result")
    if ev[:-1].any() and not sig[-1]:
        flags.append(f"the result was significant earlier (day {first + 1}) but is not at the end, "
                     "so stopping early would have produced a false positive")
    if flips >= 2:
        flags.append(f"the cumulative p-value crossed {cfg.alpha} {flips} times, so the conclusion depends on when you look")
    if cfg.planned_n_per_arm and sig[-1] and n_per_arm < 0.8 * cfg.planned_n_per_arm:
        flags.append(f"the test stopped at {n_per_arm:,} users per arm, short of the planned {cfg.planned_n_per_arm:,}")
    infl = peeking_fpr(n_days) if abs(cfg.alpha - 0.05) < 1e-9 else None
    if flags:
        msg = "Signs of peeking: " + "; ".join(flags) + "."
        if infl:
            msg += f" Checking daily for {n_days} days can raise the false-positive rate from 5% to about {infl * 100:.0f}%."
    else:
        msg = f"No sign of early stopping across {n_days} days of cumulative results."
    return CheckResult(name=name, status="warn" if flags else "pass", summary=msg,
                       details={"days": n_days, "first_significant_day": None if first is None else first + 1,
                                "crossings": flips, "inflated_false_positive_rate": infl})


# ------------------------------------------------------------------------ novelty
def check_novelty(ts: Optional[pd.DataFrame], kind: str) -> CheckResult:
    """Compare the effect in the first third of the test with the last third (inverse-variance pooled)."""
    name = "Novelty / primacy effect"
    if ts is None:
        return CheckResult(name=name, status="skipped", summary="Needs a timestamp column.")
    d = ts.dropna(subset=["daily_diff", "daily_se"])
    d = d[d["daily_se"] > 0]
    if len(d) < 7:
        return CheckResult(name=name, status="skipped", summary="Needs at least 7 days of data.")
    k = max(2, len(d) // 3)

    def pooled(sub):
        w = 1 / sub["daily_se"] ** 2
        return float((sub["daily_diff"] * w).sum() / w.sum()), float(np.sqrt(1 / w.sum()))

    (early, se_e), (late, se_l) = pooled(d.iloc[:k]), pooled(d.iloc[-k:])
    z = (late - early) / np.hypot(se_e, se_l)
    p = float(2 * stats.norm.sf(abs(z)))
    status = "pass"
    msg = (f"The effect looks stable over time (first {k} days {fmt_diff(early, kind)}, "
           f"last {k} days {fmt_diff(late, kind)}; difference p-value {p:.3f}).")
    if p < 0.01 and early != 0 and abs(late) < abs(early) and np.sign(late - early) != np.sign(early):
        status = "warn"
        msg = (f"The effect is fading: {fmt_diff(early, kind)} in the first {k} days vs "
               f"{fmt_diff(late, kind)} in the last {k} days (difference p-value {p:.4f}). "
               "This looks like a novelty effect, so the overall average overstates the long-run lift.")
    elif p < 0.01 and early != 0 and abs(late) > abs(early):
        status = "warn"
        msg = (f"The effect is growing: {fmt_diff(early, kind)} early vs {fmt_diff(late, kind)} late "
               f"(difference p-value {p:.4f}). This looks like a primacy / learning effect, "
               "so the overall average may understate the long-run lift.")
    return CheckResult(name=name, status=status, summary=msg,
                       details={"early": early, "late": late, "difference_p": p})