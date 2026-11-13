"""Stakeholder memo: LLM (Groq) constrained to verified facts, rule-based template as fallback."""
from __future__ import annotations

import json
import os

from .pipeline import AnalysisBundle
from .schemas import LLMMemoBody, Memo, MemoFacts
from .utils import fmt_diff, fmt_p, fmt_pct, fmt_val, ungrounded_numbers

HEADLINES = {"SHIP": "Ship it", "DONT_SHIP": "Don't ship", "KEEP_RUNNING": "Keep the test running"}


def _metric_facts(m, alpha: float) -> dict[str, str]:
    level = f"{round((1 - alpha) * 100)}% interval"
    return {
        "metric": m.metric,
        "control": fmt_val(m.control_value, m.kind),
        "treatment": fmt_val(m.treatment_value, m.kind),
        "absolute_difference": fmt_diff(m.abs_diff, m.kind),
        "relative_lift": fmt_pct(m.rel_lift),
        level: f"[{fmt_diff(m.ci_low, m.kind)}, {fmt_diff(m.ci_high, m.kind)}]",
        "p_value": fmt_p(m.p_value),
        "p_value_adjusted_for_multiple_tests": fmt_p(m.p_adjusted),
        "test": m.test,
        "variance_reduced_by_cuped": f"{m.variance_reduction * 100:.0f}%" if m.cuped_used else "not used",
    }


def build_facts(bundle: AnalysisBundle, variant: str) -> MemoFacts:
    cfg, r = bundle.cfg, bundle.variants[variant]
    pw = r.power
    power_note = (f"{pw.n_per_arm:,} users per arm. At {cfg.power * 100:.0f}% power the smallest relative lift "
                  f"this test could detect is {pw.achievable_mde_rel * 100:.1f}%. Detecting a "
                  f"{cfg.mde_rel * 100:.0f}% lift needs {pw.required_n_per_arm:,} users per arm.")
    return MemoFacts(
        experiment=cfg.name, variant=variant, recommendation=HEADLINES[r.decision.recommendation],
        trust=r.decision.trust,
        sample=f"{r.primary.n_control:,} control users and {r.primary.n_treatment:,} {variant} users"
               + (f" over {bundle.n_days} days" if bundle.n_days else ""),
        primary=_metric_facts(r.primary, cfg.alpha),
        guardrails=[_metric_facts(g, cfg.alpha) for g in r.guardrails],
        health_checks=[{"check": c.name, "status": c.status, "finding": c.summary}
                       for c in bundle.all_checks(variant)],
        segment_note=r.segments.warning if r.segments else "No segment analysis was run.",
        power_note=power_note, decision_reasons=r.decision.reasons)


# ------------------------------------------------------------------ template memo
def template_memo(bundle: AnalysisBundle, variant: str, note: str | None = None) -> Memo:
    cfg, r = bundle.cfg, bundle.variants[variant]
    d, f = r.decision, build_facts(bundle, variant)
    checks = bundle.all_checks(variant)
    bad = [c for c in checks if c.status in ("warn", "fail")]
    ok = [c for c in checks if c.status == "pass"]
    ci_key = next(k for k in f.primary if k.endswith("interval"))
    evidence = [f"{f.primary['metric']}: {f.primary['control']} (control) vs {f.primary['treatment']} "
                f"({variant}), a {f.primary['relative_lift']} relative change; {ci_key} "
                f"{f.primary[ci_key]}, adjusted p-value {f.primary['p_value_adjusted_for_multiple_tests']}."]
    for g in f.guardrails:
        evidence.append(f"Guardrail {g['metric']}: {g['control']} vs {g['treatment']} "
                        f"({g['absolute_difference']}, p-value {g['p_value']}).")
    evidence.append(f"{len(ok)} health check(s) passed and {len(bad)} raised a warning or failure.")
    risks = [f"{c.name} ({c.status}): {c.summary}" for c in bad]
    risks += [f"Guardrail breached: {m}." for m in d.guardrail_breaches]
    if r.segments and r.segments.n_significant_raw:
        risks.append("Segment view: " + r.segments.warning)
    if not risks:
        risks = ["No material risks found by the automated checks."]
    steps = {
        "SHIP": ["Roll out gradually and watch the primary and guardrail metrics after launch.",
                 "Keep a small holdout if you want to confirm the lift persists."],
        "DONT_SHIP": ["Do not launch this variant on the current evidence.",
                      "Fix any failed checks and rerun, or move on to the next idea."],
        "KEEP_RUNNING": [f"Continue until each arm reaches {r.power.required_n_per_arm:,} users, "
                         "and decide only at that point rather than checking daily.",
                         "Rerun the checks on the full data before deciding."],
    }[d.recommendation]
    return Memo(headline=f"{HEADLINES[d.recommendation]}: {variant} vs {cfg.control_label}",
                recommendation=d.recommendation, trust=d.trust,
                summary=" ".join(d.reasons) + f" Confidence in this result: {d.trust.lower()}.",
                evidence=evidence, risks=risks, next_steps=steps, source="template", note=note)


# ---------------------------------------------------------------------- LLM memo
SYSTEM_PROMPT = (
    "You write short decision memos about A/B tests for non-technical stakeholders. "
    "Use ONLY the facts in the JSON the user sends. Never introduce a number that is not in the JSON; "
    "copy numbers exactly as written there. Do not change or soften the recommendation. "
    "Explain jargon in plain English. Reply with a JSON object with keys: "
    "summary (2-3 sentences), key_evidence (3-5 strings), risks (list of strings), next_steps (list of strings)."
)


def _call_groq(facts: MemoFacts) -> LLMMemoBody:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": facts.model_dump_json(indent=1)}],
        temperature=0.2, max_tokens=2500, response_format={"type": "json_object"})
    return LLMMemoBody.model_validate_json(resp.choices[0].message.content)


def validate_body(body: LLMMemoBody, facts: MemoFacts) -> list[str]:
    """Numbers in the memo text that are not in the verified facts."""
    text = " ".join([body.summary, *body.key_evidence, *body.risks, *body.next_steps])
    return ungrounded_numbers(text, facts.model_dump_json())


def generate_memo(bundle: AnalysisBundle, variant: str, use_llm: bool = True) -> Memo:
    fallback = template_memo(bundle, variant)
    if not (use_llm and os.getenv("GROQ_API_KEY")):
        return fallback
    facts = build_facts(bundle, variant)
    try:
        body = _call_groq(facts)
    except Exception as exc:  # network, quota, bad JSON: never break the app
        return template_memo(bundle, variant, note=f"LLM unavailable ({type(exc).__name__}); used rule-based memo.")
    bad = validate_body(body, facts)
    if bad:
        return template_memo(bundle, variant, note="LLM memo rejected: it contained numbers not in the "
                             f"computed results ({', '.join(bad[:5])}). Used rule-based memo instead.")
    d = bundle.variants[variant].decision
    return Memo(headline=fallback.headline, recommendation=d.recommendation, trust=d.trust,
                summary=body.summary, evidence=body.key_evidence, risks=body.risks or fallback.risks,
                next_steps=body.next_steps, source="llm",
                note="Written by Groq; every number was checked against the computed results.")