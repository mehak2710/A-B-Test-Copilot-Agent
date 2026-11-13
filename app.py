"""Streamlit dashboard: upload -> map columns -> health, stats, memo, export."""
import os
import warnings

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ab_copilot import ExperimentConfig, MetricSpec, generate_memo, run_analysis
from ab_copilot.charts import fig_cumulative_p, fig_daily_lift, fig_forest, fig_segments, fig_srm
from ab_copilot.report import results_table, to_markdown, to_pdf
from ab_copilot.synthetic import SCENARIOS, make_experiment, synthetic_config

warnings.filterwarnings("ignore")
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="A/B Test Copilot", page_icon="🧪", layout="wide")
STATUS = {"pass": "✅ pass", "warn": "⚠️ warn", "fail": "❌ fail", "skipped": "⏭️ skipped"}


def guess_kind(s: pd.Series) -> str:
    return "proportion" if s.dropna().nunique() <= 2 else "mean"


def guess_idx(cols, keys, avoid=()):
    """Index of the first column whose name contains one of the keywords."""
    for k in keys:
        for i, c in enumerate(cols):
            if k in c.lower() and c not in avoid:
                return i
    return 0


def mapping_ui(df: pd.DataFrame):
    st.subheader("2 · Map your columns")
    cols = list(df.columns)
    none = "(none)"
    c1, c2, c3 = st.columns(3)
    user_col = c1.selectbox("User ID", cols, index=guess_idx(cols, ["user id", "user_id", "userid", "user", "id"]))
    variant_col = c2.selectbox("Variant / group", cols, index=guess_idx(
        cols, ["test group", "variant", "group", "arm", "bucket", "treatment"], avoid=(user_col,)))
    time_col = c3.selectbox("Timestamp (enables peeking, novelty and bot checks)", [none, *cols])
    labels = sorted(df[variant_col].dropna().astype(str).unique())
    if len(labels) > 8:
        st.error(f"'{variant_col}' has {len(labels)} distinct values; pick the column holding the variant labels.")
        return None
    c1, c2 = st.columns(2)
    control = c1.selectbox("Control label", labels)
    treatments = c2.multiselect("Treatment label(s)", [l for l in labels if l != control],
                                default=[l for l in labels if l != control][:1])

    st.markdown("**Metrics**")
    metric_cols = [c for c in cols if c not in (user_col, variant_col, time_col)]
    c1, c2, c3, c4 = st.columns(4)
    p_col = c1.selectbox("Primary metric", metric_cols)
    p_kind = c2.selectbox("Type", ["proportion", "mean", "ratio"],
                          index=["proportion", "mean", "ratio"].index(guess_kind(df[p_col])))
    p_den = c3.selectbox("Denominator (ratio only)", metric_cols) if p_kind == "ratio" else None
    p_dir = c4.selectbox("Better when", ["higher_better", "lower_better"])
    others = [c for c in metric_cols if c != p_col]
    sec_cols = st.multiselect("Secondary metrics (corrected for multiple testing)", others)
    g_cols = st.multiselect("Guardrail metrics (should not get worse)", [c for c in others if c not in sec_cols])

    def spec_row(col, key, default_dir="higher_better"):
        a, b, c = st.columns([2, 1, 1])
        a.write(f"`{col}`")
        kind = b.selectbox("type", ["proportion", "mean"], key=f"{key}k{col}",
                           index=["proportion", "mean"].index(guess_kind(df[col])), label_visibility="collapsed")
        d = c.selectbox("better when", ["higher_better", "lower_better"], key=f"{key}d{col}",
                        index=["higher_better", "lower_better"].index(default_dir), label_visibility="collapsed")
        return MetricSpec(column=col, kind=kind, direction=d)

    secondary = [spec_row(c, "s") for c in sec_cols]
    guardrails = [spec_row(c, "g", "lower_better") for c in g_cols]

    c1, c2 = st.columns(2)
    cov = c1.selectbox("Pre-experiment covariate for CUPED (optional)", [none, *metric_cols])
    segs = c2.multiselect("Segment columns (low-cardinality)", [c for c in cols if df[c].nunique() <= 12 and c not in (user_col, variant_col)])

    with st.expander("Advanced settings"):
        a, b, c = st.columns(3)
        alpha = a.number_input("Significance level (alpha)", 0.001, 0.2, 0.05, 0.005)
        power = b.slider("Power", 0.5, 0.99, 0.8)
        mde = c.number_input("Smallest relative lift worth detecting", 0.001, 1.0, 0.05, 0.005)
        a, b, c = st.columns(3)
        planned = a.number_input("Planned users per arm (0 = unknown)", 0, 10**9, 0)
        winsor = b.number_input("Winsorize mean metrics at quantile (0 = off)", 0.0, 0.9999, 0.0, 0.001)
        correction = c.selectbox("Multiple-testing correction", ["holm", "fdr_bh", "bonferroni"])
        split = None
        if st.checkbox("Intended split is not equal") and treatments:
            split = {l: st.number_input(f"Share for {l}", 0.0, 1.0, 1 / (1 + len(treatments)), key=f"split{l}")
                     for l in [control, *treatments]}
    try:
        return ExperimentConfig(
            name=st.session_state.get("exp_name", "uploaded experiment"), user_col=user_col, variant_col=variant_col,
            control_label=control, treatment_labels=treatments, time_col=None if time_col == none else time_col,
            primary=MetricSpec(column=p_col, kind=p_kind, denominator=p_den, direction=p_dir),
            secondary=secondary, guardrails=guardrails, covariate_col=None if cov == none else cov,
            segment_cols=segs, expected_split=split, alpha=alpha, power=power, mde_rel=mde,
            planned_n_per_arm=planned or None, winsorize_upper=winsor or None, correction=correction)
    except ValidationError as e:
        st.error(str(e))
        return None


@st.cache_data(show_spinner=False)
def load_synthetic(scenario: str, n: int):
    return make_experiment(scenario, n_users=n)


# ----------------------------------------------------------------------- sidebar
st.title("🧪 A/B Test Copilot")
st.caption("Checks whether the experiment can be trusted, analyzes it, then writes the ship / don't ship memo.")
with st.sidebar:
    st.header("1 · Data")
    source = st.radio("Source", ["Synthetic demo", "Upload CSV"])
    st.session_state["exp_name"] = st.text_input("Experiment name", "Checkout button test")
    use_llm = st.checkbox("Write memo with Groq", value=bool(os.getenv("GROQ_API_KEY")),
                          help="Needs GROQ_API_KEY. Falls back to a rule-based memo if unavailable or if the LLM invents numbers.")

df, cfg = None, None
up = None
if source == "Synthetic demo":
    scenario = st.sidebar.selectbox("Scenario", list(SCENARIOS), format_func=lambda k: f"{k}: {SCENARIOS[k]}")
    n_users = st.sidebar.select_slider("Users", [20_000, 40_000, 80_000, 120_000], value=80_000)
    data_key = ("synthetic", scenario, n_users)
    df = load_synthetic(scenario, n_users)
    cfg = synthetic_config(n_users, st.session_state["exp_name"])
    st.info(f"Synthetic scenario **{scenario}**: {SCENARIOS[scenario]}. The tool is not told what was planted; see if it catches it.")
else:
    up = st.sidebar.file_uploader("CSV file", type="csv")
    data_key = ("upload", up.name if up else None)
    if up:
        df = pd.read_csv(up)
        cfg = mapping_ui(df)

if st.session_state.get("data_key") != data_key:  # new data: drop results from the previous dataset
    st.session_state["data_key"] = data_key
    st.session_state.pop("bundle", None)

if df is not None:
    with st.expander(f"Preview ({len(df):,} rows)"):
        st.dataframe(df.head(50), width="stretch")

if df is not None and cfg is not None and st.button("Run analysis", type="primary"):
    with st.spinner("Checking, analyzing, deciding..."):
        try:
            st.session_state["bundle"] = run_analysis(df, cfg)
            st.session_state["memos"] = {}
        except Exception as e:  # surface config mistakes instead of a stack trace
            st.session_state.pop("bundle", None)
            st.error(f"Analysis failed: {e}")

bundle = st.session_state.get("bundle")
if bundle is None:
    st.stop()

# ----------------------------------------------------------------------- results
variant = st.selectbox("Variant", list(bundle.variants)) if len(bundle.variants) > 1 else next(iter(bundle.variants))
rep = bundle.variants[variant]
dec = rep.decision
banner = {"SHIP": st.success, "DONT_SHIP": st.error, "KEEP_RUNNING": st.warning}[dec.recommendation]
banner(f"**{dec.recommendation.replace('_', ' ')}**  ·  trust in this result: **{dec.trust}**\n\n" + " ".join(dec.reasons))

p = rep.primary
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{p.metric} (control)", f"{p.control_value * 100:.2f}%" if p.kind == "proportion" else f"{p.control_value:,.3f}")
c2.metric(f"{p.metric} ({variant})", f"{p.treatment_value * 100:.2f}%" if p.kind == "proportion" else f"{p.treatment_value:,.3f}",
          None if p.rel_lift is None else f"{p.rel_lift * 100:+.1f}%")
c3.metric("Adjusted p-value", "<0.001" if (p.p_adjusted or p.p_value) < 0.001 else f"{(p.p_adjusted or p.p_value):.3f}")
c4.metric("Health checks failing", sum(c.status == "fail" for c in bundle.all_checks(variant)))

tab_memo, tab_health, tab_stats, tab_seg, tab_export = st.tabs(["Memo", "Health checks", "Results", "Segments", "Export"])

key = f"{variant}|{use_llm}"
if key not in st.session_state["memos"]:
    with st.spinner("Writing memo..."):
        st.session_state["memos"][key] = generate_memo(bundle, variant, use_llm)
memo = st.session_state["memos"][key]

with tab_memo:
    st.subheader(memo.headline)
    st.write(memo.summary)
    st.markdown("**Evidence**\n" + "\n".join(f"- {e}" for e in memo.evidence))
    st.markdown("**Risks**\n" + "\n".join(f"- {r}" for r in memo.risks))
    st.markdown("**Next steps**\n" + "\n".join(f"- {s}" for s in memo.next_steps))
    st.caption(f"Memo source: {memo.source}. {memo.note or ''}")

with tab_health:
    checks = bundle.all_checks(variant)
    st.dataframe(pd.DataFrame([{"Check": c.name, "Status": STATUS[c.status], "Finding": c.summary} for c in checks]),
                 width="stretch", hide_index=True)
    srm = next(c for c in checks if c.name.startswith("Sample ratio"))
    st.plotly_chart(fig_srm(srm), width="stretch")
    if rep.timeseries is not None:
        a, b = st.columns(2)
        a.plotly_chart(fig_cumulative_p(rep.timeseries, bundle.cfg.alpha), width="stretch")
        b.plotly_chart(fig_daily_lift(rep.timeseries, p.kind), width="stretch")

with tab_stats:
    allres = [rep.primary, *rep.secondary, *rep.guardrails]
    st.dataframe(results_table(allres), width="stretch", hide_index=True)
    st.plotly_chart(fig_forest(allres), width="stretch")
    if p.cuped_used:
        st.success(f"CUPED cut the variance of {p.metric} by {p.variance_reduction * 100:.1f}%, "
                   "so the same data detects smaller effects.")
    pw = rep.power
    st.markdown(f"**Power.** {pw.n_per_arm:,} users per arm. Detecting a {pw.target_mde_rel * 100:.0f}% relative lift needs "
                f"{pw.required_n_per_arm:,} per arm; the smallest lift this test can reliably detect is "
                f"{pw.achievable_mde_rel * 100:.1f}%." + (f" About {pw.extra_days_needed:.0f} more days needed." if pw.extra_days_needed else ""))

with tab_seg:
    if rep.segments is None:
        st.info("Select segment columns to see breakdowns.")
    else:
        st.warning(rep.segments.warning)
        st.dataframe(pd.DataFrame([s.model_dump() for s in rep.segments.results]).round(4), width="stretch", hide_index=True)
        st.plotly_chart(fig_segments(rep.segments, p.kind), width="stretch")

with tab_export:
    md = to_markdown(bundle, variant, memo)
    st.download_button("Download Markdown", md, f"ab_report_{variant}.md", "text/markdown")
    try:
        st.download_button("Download PDF", to_pdf(md), f"ab_report_{variant}.pdf", "application/pdf")
    except Exception as e:
        st.caption(f"PDF export unavailable: {e}")
    with st.expander("Preview"):
        st.markdown(md)