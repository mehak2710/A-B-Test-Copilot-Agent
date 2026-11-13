"""Markdown + PDF export."""
from __future__ import annotations

import pandas as pd

from .memo import Memo
from .pipeline import AnalysisBundle
from .schemas import MetricResult
from .utils import fmt_diff, fmt_p, fmt_pct, fmt_val

ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skipped": "SKIPPED"}


def results_table(results: list[MetricResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "metric": r.metric, "variant": r.variant, "control": fmt_val(r.control_value, r.kind),
            "treatment": fmt_val(r.treatment_value, r.kind), "difference": fmt_diff(r.abs_diff, r.kind),
            "relative lift": fmt_pct(r.rel_lift),
            "CI": f"[{fmt_diff(r.ci_low, r.kind)}, {fmt_diff(r.ci_high, r.kind)}]",
            "p-value": fmt_p(r.p_value), "adj. p-value": fmt_p(r.p_adjusted),
            "effect size": "n/a" if r.effect_size is None else f"{r.effect_size_name} {r.effect_size:+.3f}",
            "test": r.test})
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in df.to_numpy())


def to_markdown(bundle: AnalysisBundle, variant: str, memo: Memo) -> str:
    cfg, r = bundle.cfg, bundle.variants[variant]
    out = [f"# A/B Test Report: {cfg.name}", "",
           f"**Variant:** {variant} vs {cfg.control_label}  |  **Recommendation:** {memo.recommendation}  |  "
           f"**Trust:** {memo.trust}", "", "## Memo", "", f"**{memo.headline}**", "", memo.summary, "",
           "**Evidence**", *[f"- {e}" for e in memo.evidence], "",
           "**Risks**", *[f"- {x}" for x in memo.risks], "",
           "**Next steps**", *[f"- {x}" for x in memo.next_steps], ""]
    if memo.note:
        out += [f"_{memo.note}_", ""]
    out += ["## Experiment health checks", "",
            _md_table(pd.DataFrame([{"check": c.name, "status": ICON[c.status], "finding": c.summary}
                                    for c in bundle.all_checks(variant)])), "",
            "## Results", "",
            _md_table(results_table([r.primary, *r.secondary, *r.guardrails]).drop(columns=["test"])), "",
            "Tests used: " + "; ".join(f"{m.metric}: {m.test}" for m in [r.primary, *r.secondary, *r.guardrails]) + ".", ""]
    prim = r.primary
    if prim.cuped_used:
        out += [f"CUPED reduced the variance of {prim.metric} by {prim.variance_reduction * 100:.1f}%.", ""]
    pw = r.power
    out += ["## Power", "",
            f"- Users per arm: {pw.n_per_arm:,}", f"- Required for a {pw.target_mde_rel * 100:.0f}% relative lift: {pw.required_n_per_arm:,}",
            f"- Smallest detectable relative lift at current size: {pw.achievable_mde_rel * 100:.1f}%", ""]
    if r.segments:
        seg = pd.DataFrame([{"segment": f"{s.segment_col}={s.level}", "users (c/t)": f"{s.n_control:,}/{s.n_treatment:,}",
                             "difference": fmt_diff(s.abs_diff, prim.kind), "p-value": fmt_p(s.p_value),
                             "adj. p-value": fmt_p(s.p_adjusted)} for s in r.segments.results])
        out += ["## Segments", "", r.segments.warning, "", _md_table(seg), ""]
    out += ["## Method notes", "",
            f"alpha={cfg.alpha}; multiple-comparison correction: {cfg.correction} over primary and secondary metrics; "
            "guardrails are tested without correction so real harm is not missed."]
    return "\n".join(out)


def to_pdf(markdown: str) -> bytes:
    """Plain text PDF of the markdown report (no charts)."""
    from fpdf import FPDF

    def clean(t: str) -> str:
        for a, b in {"\u2014": "-", "\u2013": "-", "\u2019": "'", "\u2265": ">=", "\u2264": "<=", "\u00d7": "x"}.items():
            t = t.replace(a, b)
        return t.replace("**", "").replace("_", " ").encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    for line in markdown.splitlines():
        if line.startswith("|---") or not line.strip():
            pdf.ln(2)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            text = line[2:]
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            text = line[3:]
        else:
            pdf.set_font("Helvetica", "", 9)
            text = line.replace("|", "  ") if line.startswith("|") else line
        pdf.multi_cell(0, 5.5, clean(text), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())