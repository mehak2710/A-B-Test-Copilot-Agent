"""Turn health checks + statistics into a ship / don't ship / keep running call."""
from __future__ import annotations

from .schemas import CheckResult, Decision, ExperimentConfig, MetricResult, PowerResult
from .stats import is_good
from .utils import fmt_diff, fmt_p, fmt_pct

TIME_CHECKS = ("Peeking / early stopping", "Novelty / primacy effect")


def decide(primary: MetricResult, guardrails: list[MetricResult], checks: list[CheckResult],
           power: PowerResult, cfg: ExperimentConfig) -> Decision:
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    p = primary.p_adjusted if primary.p_adjusted is not None else primary.p_value
    sig = p < cfg.alpha
    breaches = [g.metric for g in guardrails if g.p_value < cfg.alpha and not is_good(g)]
    lift = fmt_pct(primary.rel_lift)
    ci = f"[{fmt_diff(primary.ci_low, primary.kind)}, {fmt_diff(primary.ci_high, primary.kind)}]"

    if fails:
        names = ", ".join(c.name for c in fails)
        return Decision(recommendation="DONT_SHIP", trust="LOW", guardrail_breaches=breaches, reasons=[
            f"The experiment failed health check(s): {names}.",
            "The result cannot be trusted, whatever the p-value says. Fix the issue and rerun the test."])

    base_trust = "MEDIUM" if warns else "HIGH"
    if sig and not is_good(primary):
        return Decision(recommendation="DONT_SHIP", trust=base_trust, guardrail_breaches=breaches, reasons=[
            f"{primary.metric} moved the wrong way ({lift}, adjusted p-value {fmt_p(p)}, interval {ci})."])
    if sig:
        reasons = [f"{primary.metric} improved by {lift} (adjusted p-value {fmt_p(p)}, interval {ci})."]
        if breaches:
            return Decision(recommendation="DONT_SHIP", trust="MEDIUM", guardrail_breaches=breaches,
                            reasons=reasons + ["But guardrail metric(s) got worse: " + ", ".join(breaches) +
                                               ". The gain is not worth the harm without a closer look."])
        timing = [c.name for c in warns if c.name in TIME_CHECKS]
        if timing:
            return Decision(recommendation="KEEP_RUNNING", trust="MEDIUM", reasons=reasons + [
                "The timing checks raise doubts (" + ", ".join(timing) + "). "
                "Run to the planned sample size, or rerun, before trusting this lift."])
        return Decision(recommendation="SHIP", trust=base_trust, reasons=reasons + (
            ["Warnings exist but none invalidate the result: " + ", ".join(c.name for c in warns) + "."]
            if warns else ["All health checks passed and no guardrail was breached."]))

    # not significant
    if not power.powered:
        need = f"{power.required_n_per_arm:,}"
        extra = (f" At the current pace that is about {power.extra_days_needed:.0f} more days."
                 if power.extra_days_needed else "")
        return Decision(recommendation="KEEP_RUNNING", trust="MEDIUM", reasons=[
            f"No significant change yet ({lift}, adjusted p-value {fmt_p(p)}, interval {ci}).",
            f"The test is underpowered: {power.n_per_arm:,} users per arm, but {need} are needed to "
            f"detect a {cfg.mde_rel * 100:.0f}% relative lift.{extra}"])
    return Decision(recommendation="DONT_SHIP", trust=base_trust, reasons=[
        f"No significant change ({lift}, adjusted p-value {fmt_p(p)}, interval {ci}).",
        f"The test had enough users to detect a {cfg.mde_rel * 100:.0f}% relative lift, so any real effect is smaller than that."])