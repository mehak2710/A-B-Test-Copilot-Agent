"""Load-time cleaning plus the data-quality health checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .schemas import CheckResult, ExperimentConfig


def _numeric(s: pd.Series) -> pd.Series:
    return s.astype(int) if s.dtype == bool else pd.to_numeric(s, errors="coerce")


def _high_outliers(x: pd.Series, thresh: float = 6.0) -> pd.Series:
    """Boolean mask of extreme upper-tail values (robust z-score on log scale for non-negative data)."""
    v = x.dropna()
    nz = v[v != 0]
    mask = pd.Series(False, index=x.index)
    if len(nz) < 50:
        return mask
    t = np.log1p(nz.abs()) if (v >= 0).all() else nz
    med = t.median()
    mad = (t - med).abs().median() * 1.4826
    if mad == 0:
        return mask
    mask.loc[t.index[(t - med) > thresh * mad]] = True
    return mask


def prepare(raw: pd.DataFrame, cfg: ExperimentConfig) -> tuple[pd.DataFrame, list[CheckResult]]:
    vc, uc = cfg.variant_col, cfg.user_col
    labels = [cfg.control_label, *cfg.treatment_labels]
    df = raw.copy()
    df[vc] = df[vc].astype(str)
    df = df[df[vc].isin(labels)]

    metric_specs = [cfg.primary, *cfg.secondary, *cfg.guardrails]
    num_cols = {s.column for s in metric_specs} | {s.denominator for s in metric_specs if s.denominator}
    if cfg.covariate_col:
        num_cols.add(cfg.covariate_col)
    for c in num_cols:
        df[c] = _numeric(df[c])
    if cfg.time_col:
        df[cfg.time_col] = pd.to_datetime(df[cfg.time_col], errors="coerce")

    checks = [_check_duplicates(df, cfg), _check_missing(df, cfg)]

    # cleaning: drop users seen in several arms, then repeated rows
    n_arms = df.groupby(uc)[vc].nunique()
    df = df[~df[uc].isin(n_arms[n_arms > 1].index)].drop_duplicates(subset=[uc], keep="first")
    df = df.dropna(subset=[cfg.primary.column])

    checks += [_check_outliers(df, cfg), _check_bots(df, cfg)]

    if cfg.winsorize_upper:
        for s in metric_specs:
            if s.kind == "mean":
                df[s.column] = df[s.column].clip(upper=df[s.column].quantile(cfg.winsorize_upper))
    return df.reset_index(drop=True), checks


# ------------------------------------------------------------------------ checks
def _check_duplicates(df: pd.DataFrame, cfg: ExperimentConfig) -> CheckResult:
    uc, vc = cfg.user_col, cfg.variant_col
    n_rows, n_users = len(df), df[uc].nunique()
    dup_rows = int(df.duplicated(subset=[uc]).sum())
    both = int((df.groupby(uc)[vc].nunique() > 1).sum())
    dup_share, both_share = dup_rows / n_rows, both / max(n_users, 1)
    if both_share > 0.005 or dup_share > 0.05:
        status = "fail"
    elif both > 0 or dup_share > 0.005:
        status = "warn"
    else:
        status = "pass"
    return CheckResult(
        name="Duplicate users", status=status,
        summary=(f"{dup_rows} repeated user rows ({dup_share * 100:.2f}% of rows) and {both} users "
                 f"({both_share * 100:.2f}%) seen in more than one variant. "
                 "Contaminated users are dropped and repeated rows keep the first record."),
        details={"duplicate_rows": dup_rows, "contaminated_users": both})


def _check_missing(df: pd.DataFrame, cfg: ExperimentConfig) -> CheckResult:
    cols = [cfg.primary.column] + [g.column for g in cfg.guardrails]
    share = df[cols].isna().mean()
    worst_col, worst = share.idxmax(), float(share.max())
    p_arm = None
    if worst > 0:
        tab = pd.crosstab(df[cfg.variant_col], df[worst_col].isna())
        if tab.shape == (len(tab), 2):
            p_arm = float(stats.chi2_contingency(tab)[1])
    differential = p_arm is not None and p_arm < 0.001 and worst > 0.01
    status = "fail" if (worst > 0.10 or differential) else "warn" if worst > 0.01 else "pass"
    msg = f"Highest missing share is {worst * 100:.2f}% (column {worst_col})."
    if differential:
        by_arm = df.groupby(cfg.variant_col)[worst_col].apply(lambda s: s.isna().mean() * 100)
        msg += " Missingness differs by arm (" + ", ".join(f"{k}: {v:.2f}%" for k, v in by_arm.items()) + \
               "), which points to a tracking problem rather than random loss."
    return CheckResult(name="Missing values", status=status, summary=msg,
                       details={"worst_column": worst_col, "worst_share": worst, "arm_imbalance_p": p_arm})


def _check_outliers(df: pd.DataFrame, cfg: ExperimentConfig) -> CheckResult:
    findings, status, worst = [], "pass", 0.0
    for s in [cfg.primary, *cfg.guardrails]:
        if s.kind != "mean":
            continue
        mask = _high_outliers(df[s.column])
        share = float(mask.mean())
        if share <= 0:
            continue
        tab = pd.crosstab(df[cfg.variant_col], mask)
        p_arm = float(stats.chi2_contingency(tab)[1]) if tab.shape[1] == 2 else 1.0
        lvl = "fail" if (p_arm < 0.001 and share > 0.001) else "warn" if share > 0.001 else "pass"
        status = max(status, lvl, key=["pass", "warn", "fail"].index)
        worst = max(worst, share)
        findings.append(f"{s.column}: {share * 100:.2f}% extreme values (arm imbalance p={p_arm:.3f})")
    if not any(s.kind == "mean" for s in [cfg.primary, *cfg.guardrails]):
        return CheckResult(name="Outliers", status="skipped", summary="No continuous metrics to check.")
    if not findings:
        return CheckResult(name="Outliers", status="pass", summary="No extreme values found.")
    return CheckResult(
        name="Outliers", status=status,
        summary="; ".join(findings) + ". Consider capping with the winsorize option.",
        details={"worst_share": worst})


def _check_bots(df: pd.DataFrame, cfg: ExperimentConfig) -> CheckResult:
    if not cfg.time_col:
        return CheckResult(name="Bot-like traffic", status="skipped",
                           summary="Needs a timestamp column to look for traffic bursts.")
    t = df[cfg.time_col].dropna()
    if t.dt.normalize().nunique() < 3:
        return CheckResult(name="Bot-like traffic", status="skipped",
                           summary="Fewer than 3 days of data; cannot compare hour-of-day patterns.")
    counts = t.dt.floor("h").value_counts()
    typical = counts.groupby(counts.index.hour).transform("median").clip(lower=1)
    excess = counts - typical
    spike = (counts > 3 * typical) & (excess > 6 * np.sqrt(typical))
    share = float(excess[spike].sum() / len(t))
    status = "fail" if share > 0.01 else "warn" if share > 0.002 else "pass"
    if spike.any():
        hours = ", ".join(str(h) for h in counts.index[spike][:3])
        msg = (f"{int(spike.sum())} hour(s) have traffic far above their usual level "
               f"(e.g. {hours}), about {share * 100:.2f}% of users. Possible bot or crawler burst.")
    else:
        msg = "No abnormal traffic bursts found."
    return CheckResult(name="Bot-like traffic", status=status, summary=msg,
                       details={"burst_hours": int(spike.sum()), "burst_share": share})