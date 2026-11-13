import warnings

import numpy as np
import pandas as pd
import pytest

from ab_copilot import generate_memo, run_analysis
from ab_copilot.memo import build_facts, validate_body
from ab_copilot.schemas import LLMMemoBody
from ab_copilot.stats import cuped_adjust, required_n_per_arm
from ab_copilot.synthetic import make_experiment, synthetic_config
from ab_copilot.utils import ungrounded_numbers

warnings.filterwarnings("ignore")


def run(s):
    return run_analysis(make_experiment(s), synthetic_config())


def status(b, prefix):
    return next(c.status for c in b.all_checks("treatment") if c.name.startswith(prefix))


def test_clean_win_ships():
    b = run("clean_win")
    assert b.variants["treatment"].decision.recommendation == "SHIP"
    assert all(c.status in ("pass", "skipped") for c in b.all_checks("treatment"))


def test_clean_null_does_not_ship():
    assert run("clean_null").variants["treatment"].decision.recommendation != "SHIP"


def test_srm_caught():
    b = run("srm")
    assert status(b, "Sample ratio") == "fail"
    assert b.variants["treatment"].decision.recommendation == "DONT_SHIP"
    assert b.variants["treatment"].decision.trust == "LOW"


def test_peeking_caught():
    b = run("peeking")
    assert status(b, "Peeking") == "warn"
    assert b.variants["treatment"].decision.recommendation == "KEEP_RUNNING"


def test_novelty_caught():
    assert status(run("novelty"), "Novelty") == "warn"


def test_dirty_data_caught():
    b = run("dirty_data")
    for name in ("Duplicate", "Missing", "Bot"):
        assert status(b, name) == "fail"
    assert b.variants["treatment"].decision.trust == "LOW"


def test_guardrail_breach_blocks_ship():
    d = run("guardrail_breach").variants["treatment"].decision
    assert d.recommendation == "DONT_SHIP" and "refunded" in d.guardrail_breaches


def test_cuped_reduces_variance():
    rng = np.random.default_rng(0)
    x = rng.normal(size=5000)
    y = 2 * x + rng.normal(size=5000)
    _, theta, vr = cuped_adjust(y, x)
    assert abs(theta - 2) < 0.1 and vr > 0.7


def test_required_sample_size_matches_textbook():
    # 5% -> 5.5% at 80% power, alpha .05 is roughly 31k per arm
    assert 29_000 < required_n_per_arm(0.05, 0.10, 0.05, 0.8, "proportion") < 33_000


def test_ratio_metric_runs():
    rng = np.random.default_rng(1)
    n = 4000
    df = pd.DataFrame({"u": range(n), "v": rng.choice(["a", "b"], n), "orders": rng.poisson(2, n) + 1})
    df["revenue"] = df["orders"] * rng.lognormal(3, .3, n)
    from ab_copilot import ExperimentConfig, MetricSpec
    cfg = ExperimentConfig(user_col="u", variant_col="v", control_label="a", treatment_labels=["b"],
                           primary=MetricSpec(column="revenue", kind="ratio", denominator="orders"))
    r = run_analysis(df, cfg).variants["b"].primary
    assert r.test.startswith("delta-method") and 0 <= r.p_value <= 1


def test_memo_grounding_rejects_invented_numbers():
    b = run("clean_win")
    facts = build_facts(b, "treatment")
    good = LLMMemoBody(summary=f"Conversion went from {facts.primary['control']} to {facts.primary['treatment']}.",
                       key_evidence=[], risks=[], next_steps=[])
    bad = LLMMemoBody(summary="Conversion rose by 47.3% which is huge.", key_evidence=[], risks=[], next_steps=[])
    assert validate_body(good, facts) == []
    assert "47.3" in validate_body(bad, facts)


def test_ungrounded_numbers_tolerates_rounding():
    assert ungrounded_numbers("lift of 5.2%", "relative_lift: +5.23%") == []
    assert ungrounded_numbers("lift of 9%", "relative_lift: +5.23%") == ["9"]


def test_template_memo_has_no_ungrounded_numbers_and_works_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    m = generate_memo(run("clean_win"), "treatment")
    assert m.source == "template" and m.recommendation == "SHIP"