"""Synthetic experiments with deliberately planted flaws (for demos and tests)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .schemas import ExperimentConfig, MetricSpec

SCENARIOS = {
    "clean_win": "Well-run test with a real +15% conversion lift",
    "clean_null": "Well-run test where the change does nothing",
    "srm": "Treatment silently loses ~8% of its non-converting users (SRM + fake lift)",
    "peeking": "No real effect, but stopped the first day the p-value dipped below 0.05",
    "novelty": "Big early lift that decays to almost nothing",
    "dirty_data": "Duplicates, users in both arms, differential missing data, a bot burst",
    "guardrail_breach": "Conversion up +15%, but refunds more than double",
}
_LIFT = {"clean_win": .15, "clean_null": 0., "srm": .10, "peeking": 0., "novelty": .6,
         "dirty_data": .10, "guardrail_breach": .15}


def _base(scenario: str, n: int, days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-05")
    offset = rng.uniform(0, days, n)
    day_idx = offset.astype(int)
    treat = rng.random(n) < 0.5
    activity = rng.lognormal(0, 0.6, n)  # latent engagement, drives the CUPED covariate
    effect = _LIFT[scenario] * (np.exp(-day_idx / 3.0) if scenario == "novelty" else 1.0)
    logit = -3.0 + 1.8 * np.log(activity) + np.log1p(effect) * treat
    converted = rng.random(n) < 1 / (1 + np.exp(-logit))
    refund_rate = 0.08 * (2.5 if scenario == "guardrail_breach" else 1.0)
    refunded = converted & (rng.random(n) < np.where(treat, refund_rate, 0.08))
    return pd.DataFrame({
        "user_id": np.arange(1, n + 1),
        "variant": np.where(treat, "treatment", "control"),
        "timestamp": start + pd.to_timedelta(offset, unit="D"),
        "converted": converted.astype(int),
        "revenue": np.round(converted * rng.lognormal(3.4, 0.5, n), 2),
        "refunded": refunded.astype(int),
        "pre_sessions": rng.poisson(5 * activity),
        "device": rng.choice(["mobile", "desktop", "tablet"], n, p=[.6, .32, .08]),
        "user_type": rng.choice(["new", "returning"], n, p=[.45, .55]),
        "country": rng.choice(["US", "IN", "DE", "BR"], n, p=[.4, .25, .2, .15]),
        "_day": day_idx,
    })


def _peeking(n: int, days: int, seed: int) -> pd.DataFrame:
    """Find a null experiment and truncate it at the first day the p-value dips under 0.05."""
    for s in range(seed, seed + 500):
        df = _base("peeking", n, days, s)
        for d in range(3, days + 1):
            sub = df[df["_day"] < d]
            a, b = sub[sub.variant == "control"].converted, sub[sub.variant == "treatment"].converted
            pooled = sub.converted.mean()
            se = np.sqrt(pooled * (1 - pooled) * (1 / len(a) + 1 / len(b)))
            z = (b.mean() - a.mean()) / se
            if 2 * stats.norm.sf(abs(z)) < 0.05:
                if d >= 4 and z > 0:
                    return sub
                break
    return _base("peeking", n, days, seed)


def make_experiment(scenario: str = "clean_win", n_users: int = 80_000, days: int = 14,
                    seed: int = 1) -> pd.DataFrame:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose from {list(SCENARIOS)}")
    rng = np.random.default_rng(seed + 1000)
    df = _peeking(n_users, days, seed) if scenario == "peeking" else _base(scenario, n_users, days, seed)

    if scenario == "srm":
        drop = (df.variant == "treatment") & (df.converted == 0) & (rng.random(len(df)) < 0.08)
        df = df[~drop]

    if scenario == "dirty_data":
        n = len(df)
        df = df.copy()
        # tracking bug: conversion missing far more often in treatment
        miss = rng.random(n) < np.where(df.variant == "treatment", 0.03, 0.005)
        df["converted"] = df["converted"].astype(float).mask(miss)
        df["revenue"] = df["revenue"].mask(rng.random(n) < 0.015)
        dups = df.sample(frac=0.03, random_state=seed)
        flipped = df.sample(frac=0.008, random_state=seed + 1).copy()
        flipped["variant"] = np.where(flipped.variant == "control", "treatment", "control")
        k = int(0.015 * n)
        bots = df.sample(k, random_state=seed + 2).copy()
        bots["user_id"] = np.arange(n + 1, n + 1 + k)
        bots["variant"] = np.where(rng.random(k) < 0.8, "treatment", "control")
        bots["timestamp"] = pd.Timestamp("2026-01-05") + pd.Timedelta(days=6, hours=14) + \
            pd.to_timedelta(rng.uniform(0, 3600, k), unit="s")
        bots["converted"], bots["pre_sessions"] = 1.0, 0
        bots["revenue"], bots["refunded"] = np.round(rng.lognormal(7, 0.3, k), 2), 0
        df = pd.concat([df, dups, flipped, bots])

    df = df.drop(columns="_day").sort_values("timestamp").reset_index(drop=True)
    return df


def synthetic_config(n_users: int = 80_000, name: str = "synthetic experiment") -> ExperimentConfig:
    return ExperimentConfig(
        name=name, user_col="user_id", variant_col="variant", control_label="control",
        treatment_labels=["treatment"], time_col="timestamp",
        primary=MetricSpec(column="converted", kind="proportion"),
        guardrails=[MetricSpec(column="refunded", kind="proportion", direction="lower_better"),
                    MetricSpec(column="revenue", kind="mean")],
        covariate_col="pre_sessions", segment_cols=["device", "user_type", "country"],
        mde_rel=0.10, planned_n_per_arm=n_users // 2)