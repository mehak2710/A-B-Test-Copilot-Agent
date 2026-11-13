"""Pydantic models: the contract between every layer of the app."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

MetricKind = Literal["proportion", "mean", "ratio"]
Direction = Literal["higher_better", "lower_better"]
Status = Literal["pass", "warn", "fail", "skipped"]
Recommendation = Literal["SHIP", "DONT_SHIP", "KEEP_RUNNING"]


class MetricSpec(BaseModel):
    column: str
    kind: MetricKind = "proportion"
    denominator: Optional[str] = None  # ratio metrics: column / denominator
    direction: Direction = "higher_better"
    use_cuped: bool = True

    @model_validator(mode="after")
    def _ratio_needs_denominator(self):
        if self.kind == "ratio" and not self.denominator:
            raise ValueError("ratio metrics need a denominator column")
        return self


class ExperimentConfig(BaseModel):
    name: str = "experiment"
    user_col: str
    variant_col: str
    control_label: str
    treatment_labels: list[str] = Field(min_length=1)
    time_col: Optional[str] = None
    primary: MetricSpec
    secondary: list[MetricSpec] = Field(default_factory=list)  # corrected together with primary
    guardrails: list[MetricSpec] = Field(default_factory=list)  # harm checks, deliberately NOT corrected
    covariate_col: Optional[str] = None  # pre-experiment covariate for CUPED
    segment_cols: list[str] = Field(default_factory=list)
    expected_split: Optional[dict[str, float]] = None  # default: equal split
    alpha: float = 0.05
    power: float = 0.8
    mde_rel: float = 0.05  # smallest relative lift worth detecting
    planned_n_per_arm: Optional[int] = None
    winsorize_upper: Optional[float] = None  # e.g. 0.999 caps mean-metric outliers
    correction: Literal["holm", "fdr_bh", "bonferroni"] = "holm"


class CheckResult(BaseModel):
    name: str
    status: Status
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class MetricResult(BaseModel):
    metric: str
    kind: MetricKind
    variant: str
    direction: Direction
    n_control: int
    n_treatment: int
    control_value: float
    treatment_value: float
    abs_diff: float
    se_diff: float
    ci_low: float
    ci_high: float
    rel_lift: Optional[float] = None
    ci_rel_low: Optional[float] = None
    ci_rel_high: Optional[float] = None
    p_value: float
    p_adjusted: Optional[float] = None
    effect_size: Optional[float] = None
    effect_size_name: Optional[str] = None
    test: str
    cuped_used: bool = False
    variance_reduction: Optional[float] = None
    control_sd: Optional[float] = None


class PowerResult(BaseModel):
    baseline: float
    n_per_arm: int
    target_mde_rel: float
    required_n_per_arm: int
    achievable_mde_rel: Optional[float] = None
    powered: bool
    extra_days_needed: Optional[float] = None


class SegmentResult(BaseModel):
    segment_col: str
    level: str
    n_control: int
    n_treatment: int
    abs_diff: float
    se_diff: float
    rel_lift: Optional[float] = None
    ci_low: float
    ci_high: float
    p_value: float
    p_adjusted: Optional[float] = None


class SegmentReport(BaseModel):
    results: list[SegmentResult]
    heterogeneity_p: dict[str, float]  # per segment column (Cochran's Q)
    n_tested: int
    familywise_false_positive_risk: float
    n_significant_raw: int
    n_significant_adjusted: int
    warning: str


class Decision(BaseModel):
    recommendation: Recommendation
    trust: Literal["HIGH", "MEDIUM", "LOW"]
    reasons: list[str]
    guardrail_breaches: list[str] = Field(default_factory=list)


class MemoFacts(BaseModel):
    """Everything the memo is allowed to say. All numbers are pre-formatted strings."""
    experiment: str
    variant: str
    recommendation: str
    trust: str
    sample: str
    primary: dict[str, str]
    guardrails: list[dict[str, str]]
    health_checks: list[dict[str, str]]
    segment_note: str
    power_note: str
    decision_reasons: list[str]


class LLMMemoBody(BaseModel):
    summary: str
    key_evidence: list[str]
    risks: list[str]
    next_steps: list[str]


class Memo(BaseModel):
    headline: str
    recommendation: Recommendation
    trust: str
    summary: str
    evidence: list[str]
    risks: list[str]
    next_steps: list[str]
    source: Literal["llm", "template"]
    note: Optional[str] = None