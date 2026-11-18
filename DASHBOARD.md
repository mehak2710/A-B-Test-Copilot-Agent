# Dashboard Guide

A complete walkthrough of the A/B Test Copilot dashboard: what every control does, what every output means, and how to read it.

Start the dashboard with:

```bash
python -m streamlit run app.py
```

## Contents

1. [Page layout at a glance](#page-layout-at-a-glance)
2. [Sidebar: choosing your data](#sidebar-choosing-your-data)
3. [Mapping your columns](#mapping-your-columns)
4. [Advanced settings](#advanced-settings)
5. [Running the analysis](#running-the-analysis)
6. [The decision banner and summary cards](#the-decision-banner-and-summary-cards)
7. [Memo tab](#memo-tab)
8. [Health checks tab](#health-checks-tab)
9. [Results tab](#results-tab)
10. [Segments tab](#segments-tab)
11. [Export tab](#export-tab)
12. [Glossary](#glossary)
13. [Troubleshooting](#troubleshooting)

---

## Page layout at a glance

```
┌─ Sidebar ─────────┐ ┌─ Main area ───────────────────────────────────────────┐
│ 1 · Data          │ │ Title                                                 │
│  Source           │ │ 2 · Map your columns   (upload mode only)             │
│  Experiment name  │ │ Preview of your data                                  │
│  Write memo w/Groq│ │ [Run analysis]                                        │
│  Scenario / CSV   │ │ Decision banner  →  4 summary cards                   │
└───────────────────┘ │ Tabs: Memo | Health checks | Results | Segments | Export│
                      └───────────────────────────────────────────────────────┘
```

---

## Sidebar: choosing your data

| Control | What it does |
|---|---|
| **Source** | `Synthetic demo` builds an experiment with a planted flaw for you to test the tool on. `Upload CSV` lets you analyze your own data. |
| **Experiment name** | A label used in the memo and the exported report. |
| **Write memo with Groq** | When ticked, the memo is written by the Groq language model. It is ticked by default only if a `GROQ_API_KEY` is set. Untick it to use the rule-based memo. If Groq is unavailable or invents a number, the app falls back to the rule-based memo automatically. |
| **Scenario** *(demo only)* | Picks one of seven synthetic experiments, each with a planted flaw (see below). |
| **Users** *(demo only)* | Sample size of the synthetic experiment: 20,000 to 120,000. Smaller samples make the test less powerful. |
| **CSV file** *(upload only)* | Your experiment data. Choosing a new file or switching source clears the previous results. |

### Synthetic scenarios

| Scenario | What was planted | What the dashboard should show |
|---|---|---|
| `clean_win` | A real +15% conversion lift | SHIP, high trust |
| `clean_null` | No effect at all | Not SHIP |
| `srm` | Treatment loses ~8% of non-converters | SRM check fails, DON'T SHIP, low trust |
| `peeking` | No effect, stopped when p first dipped below 0.05 | Peeking warning, KEEP RUNNING |
| `novelty` | Big early lift that fades | Novelty warning, KEEP RUNNING |
| `dirty_data` | Duplicates, users in both arms, differential missing data, bot burst | Several failed checks, low trust |
| `guardrail_breach` | Conversion up but refunds more than double | DON'T SHIP |

The synthetic demo skips the column-mapping step because it already knows its own columns.

---

## Mapping your columns

Shown only in **Upload CSV** mode. The app guesses sensible defaults from column names, but check each one.

### Identity and timing

| Field | Meaning |
|---|---|
| **User ID** | The column that uniquely identifies each user. Used to find duplicates and users who appear in both groups. |
| **Variant / group** | The column that says which group each user was in. It must have few distinct values (8 or fewer). If you pick a column with many values, the app shows an error. |
| **Timestamp (optional)** | When each user entered the experiment. Turns on the **peeking**, **novelty** and **bot-traffic** checks. Leave as `(none)` if your data has no entry time. |

### Groups

| Field | Meaning |
|---|---|
| **Control label** | The value in the variant column that marks the control (baseline) group. |
| **Treatment label(s)** | One or more values that mark the variant(s) being tested against control. With several treatments, a **Variant** selector appears above the results, and p-values are corrected for the extra comparisons. |

### Metrics

| Field | Meaning |
|---|---|
| **Primary metric** | The one outcome the test was designed to move, for example `converted`. |
| **Type** | `proportion` (yes/no per user, like converted), `mean` (a number per user, like revenue), or `ratio` (a total divided by another total, like revenue per order). |
| **Denominator** *(ratio only)* | The column to divide by. |
| **Better when** | `higher_better` or `lower_better`. Decides which direction counts as good. |
| **Secondary metrics** | Extra outcomes you care about. Their p-values are corrected together with the primary metric to prevent false positives from testing many things. |
| **Guardrail metrics** | Things that should not get worse, for example refund rate. Each gets a type and a "better when" setting (guardrails default to `lower_better`). Guardrails are tested without correction on purpose, so real harm is not missed. |

### Optional extras

| Field | Meaning |
|---|---|
| **Pre-experiment covariate for CUPED** | A column measured *before* the experiment that predicts the outcome (for example, past sessions). It reduces noise so smaller effects can be detected. Leave as `(none)` if you don't have one. |
| **Segment columns** | Columns to break the result down by, for example device or country. Only columns with 12 or fewer distinct values are offered. |

---

## Advanced settings

Open the **Advanced settings** expander.

| Setting | Default | Meaning |
|---|---|---|
| **Significance level (alpha)** | 0.05 | The false-positive rate you accept. Results with p-values below this are "significant". |
| **Power** | 0.80 | The chance of detecting a real effect of the target size. Used for sample-size and power calculations. |
| **Smallest relative lift worth detecting** | 0.05 (5%) | The minimum improvement that would matter to your business. Drives the "required sample size" and decides whether a non-significant result means "no effect" or "not enough data". |
| **Planned users per arm** | 0 (unknown) | If you set it, the peeking check can flag a test that stopped well short of plan. |
| **Winsorize mean metrics at quantile** | 0 (off) | Caps extreme values at this quantile (for example 0.999) so a few huge values don't dominate a mean-based metric. |
| **Multiple-testing correction** | holm | `holm` (strong, recommended), `fdr_bh` (less strict, controls the false-discovery rate), or `bonferroni` (strictest). |
| **Intended split is not equal** | off | Tick it if the groups were *meant* to be unequal, then enter the intended share for each group. Without this, a deliberately unbalanced test fails the sample-ratio check. |

---

## Running the analysis

Click **Run analysis**. The app cleans the data, runs the health checks, computes the statistics, applies the decision rules, and writes the memo. Results stay on screen until you switch data, so you can click between tabs freely.

If something is misconfigured (for example a text column chosen as a numeric metric), a red "Analysis failed" message explains why instead of crashing.

---

## The decision banner and summary cards

### Decision banner

| Colour | Recommendation | Meaning |
|---|---|---|
| 🟩 Green | **SHIP** | The result is significant, in the good direction, and nothing invalidates it. |
| 🟥 Red | **DON'T SHIP** | A failed health check, a harmful result, a breached guardrail, or a well-powered test that found no meaningful effect. |
| 🟧 Orange | **KEEP RUNNING** | The test is underpowered, or timing checks (peeking, novelty) make the result unreliable. |

The banner also shows the **trust level** and the plain-English reasons.

| Trust | Meaning |
|---|---|
| **HIGH** | All health checks passed. |
| **MEDIUM** | Some warnings exist, but none invalidate the result. |
| **LOW** | At least one health check failed, so the result cannot be relied on. |

### Summary cards

| Card | Meaning |
|---|---|
| **Primary metric (control)** | The control group's value. |
| **Primary metric (variant)** | The treatment's value, with the relative lift shown underneath. |
| **Adjusted p-value** | The p-value after correction for multiple tests. Below alpha means statistically significant. |
| **Health checks failing** | Number of failed checks. Anything above 0 means the result is untrustworthy. |

---

## Memo tab

A stakeholder-ready write-up of the result.

| Section | Contents |
|---|---|
| **Headline** | The recommendation in one line. It is set by the code, not the language model. |
| **Summary** | Two or three sentences with the reasoning. |
| **Evidence** | The key numbers: control vs treatment, the confidence interval, the adjusted p-value, and each guardrail. |
| **Risks** | Every health-check warning or failure, any breached guardrail, and a segment warning if relevant. |
| **Next steps** | What to do: roll out gradually, fix and rerun, or keep running to a stated sample size. |
| **Caption** | Whether the memo came from `llm` (Groq) or `template`, plus a note. |

**How the memo stays honest.** The language model only sees pre-formatted facts. Every number in its output is checked against those facts. If it invents one, the memo is rejected and the rule-based template is used instead, and the caption tells you so.

---

## Health checks tab

The first question the tool answers is "can I trust this experiment?".

### The check table

Each row shows the check, its status, and a plain-English finding.

| Status | Meaning |
|---|---|
| ✅ **pass** | Nothing wrong found. |
| ⚠️ **warn** | A concern worth knowing about; it may lower trust or change the recommendation. |
| ❌ **fail** | A serious problem. The result cannot be trusted and the recommendation becomes DON'T SHIP. |
| ⏭️ **skipped** | Not enough information (for example no timestamp column). |

### What each check does

| Check | What it looks for | Fail / warn thresholds |
|---|---|---|
| **Sample ratio mismatch (SRM)** | Whether the number of users per group matches the intended split (chi-square test) | Fail if p < 0.001, warn if p < 0.01 |
| **Duplicate users** | Repeated user rows, and users who appear in more than one group. Contaminated users are dropped; repeated rows keep the first record. | Fail if over 0.5% of users are in both groups or over 5% of rows are repeats. Warn on any contamination or over 0.5% repeats. |
| **Missing values** | Missing data in the metric columns, and whether it differs between groups | Fail if over 10% missing, or if missingness differs by group (a tracking problem). Warn if over 1%. |
| **Outliers** | Extreme high values in mean-based metrics | Warn if over 0.1% are extreme. Fail only if the extremes are lopsided between groups. Consider the winsorize setting. |
| **Bot-like traffic** | Hours with far more traffic than that hour usually gets | Fail if bursts exceed 1% of users, warn over 0.2% |
| **Peeking / early stopping** | The test ending right after the p-value first dipped below alpha, a p-value that flips across alpha repeatedly, or stopping short of the planned sample | Warn only. This check can show signs of peeking but cannot prove it. |
| **Novelty / primacy effect** | Whether the effect in the first third of the test differs from the last third | Warn if the difference is significant (p < 0.01). A fading effect is novelty; a growing one is primacy or learning. |

### Charts

| Chart | How to read it |
|---|---|
| **Users per variant: expected vs observed** | Two bars per group. They should be nearly equal. A visible gap matches an SRM failure. |
| **Cumulative p-value by day** | The p-value you would have seen if you checked every day. The dashed red line is alpha. If the line dips below it only briefly, or just before the test ends, that is the peeking pattern. A trustworthy result stays well below the line for a sustained period. |
| **Daily difference with 95% bars** | Treatment minus control for each day. A line that starts high and slides toward zero is a novelty effect. Bars that mostly cross zero mean no clear daily effect. |

The two time charts appear only when you provide a timestamp column and the metric is a proportion or mean.

---

## Results tab

The statistics, once the experiment is judged trustworthy.

### Results table

One row per metric (primary, then secondary, then guardrails).

| Column | Meaning |
|---|---|
| **metric / variant** | Which metric and which treatment. |
| **control / treatment** | Each group's value. Proportions are shown as percentages. |
| **difference** | Treatment minus control. `pp` means percentage points. |
| **relative lift** | The difference as a percentage of the control value. |
| **CI** | The confidence interval for the difference. If it excludes zero, the result is significant. A wide interval means high uncertainty. |
| **p-value** | The chance of seeing a difference this large if there were truly no effect. |
| **adj. p-value** | The p-value after multiple-testing correction. Shown for the primary and secondary metrics; guardrails show `n/a` because they are deliberately not corrected. |
| **effect size** | A standardised size: Cohen's h for proportions, Cohen's d for means. Rough guide: 0.2 small, 0.5 medium, 0.8 large. |
| **test** | Which test was used for that metric. |

### Forest plot

Each dot is a metric's relative lift and each bar its confidence interval. Bars that cross the dotted zero line are not significant. This shows the size of the effect and the uncertainty at a glance.

### CUPED message

If a pre-experiment covariate was used, a green message says how much it cut the variance (for example 6.4%). More variance reduction means the same data can detect smaller effects.

### Power paragraph

| Item | Meaning |
|---|---|
| **Users per arm** | Your current sample in the smaller group. |
| **Required for the target lift** | The users per arm needed to reliably detect your "smallest relative lift worth detecting". |
| **Smallest lift this test can detect** | The minimum effect your current sample could reliably find. |
| **Extra days needed** | Shown if you are short of the target and have timestamps. |

---

## Segments tab

Breaks the primary metric down by the segment columns you chose (for example device or country). Shown only if you selected segment columns.

| Element | Meaning |
|---|---|
| **Warning box** | States how many segment cuts were tested, the resulting chance of at least one false positive, and how many look significant before and after correction. This is the guard against cherry-picking. |
| **Table** | Per-segment sample sizes, difference, confidence interval, p-value and adjusted p-value. Segments with fewer than 200 users in either group are skipped. |
| **Chart** | Each segment's effect with a confidence interval. Red marks a segment that is significant after correction; grey is not. |

**How to use it:** treat segment differences as hypotheses to test in a follow-up experiment, not as grounds to ship or kill the change for one segment. The heterogeneity test mentioned in the warning says whether effects genuinely differ across a segment column. If it is not significant, the differences you see are consistent with noise.

---

## Export tab

| Control | What it does |
|---|---|
| **Download Markdown** | A full report with the memo, health checks, results, power, and segments. |
| **Download PDF** | The same report as text-only PDF (charts are not included). |
| **Preview** | An expandable preview of the Markdown report. |

The report is for the variant currently selected. With several treatments, export each one separately.

---

## Glossary

| Term | Plain-English meaning |
|---|---|
| **A/B test** | An experiment that randomly splits users into a control group and one or more variants to measure the effect of a change. |
| **SRM (sample ratio mismatch)** | The groups are not the size they were meant to be, which usually signals a bug and invalidates the test. |
| **Peeking** | Checking results repeatedly and stopping at the first significant one, which inflates false positives. |
| **Novelty effect** | A lift that fades because users reacted to the newness of the change. |
| **Primacy effect** | A lift that grows as users learn the new experience. |
| **p-value** | How surprising the result would be if the change did nothing. Small values suggest a real effect. |
| **Adjusted p-value** | The p-value corrected for running many comparisons. |
| **Confidence interval (CI)** | The range of effect sizes consistent with the data. |
| **Relative lift** | The change as a percentage of the control value. |
| **pp (percentage points)** | The absolute difference between two percentages (7.2% to 8.0% is +0.8 pp). |
| **Effect size** | The size of the effect in standardised units, independent of sample size. |
| **CUPED** | A variance-reduction technique that uses pre-experiment behaviour to remove noise. |
| **Power** | The probability of detecting a real effect of a given size. |
| **Smallest worthwhile lift (MDE)** | The smallest improvement you would care about. |
| **Guardrail metric** | A metric that must not get worse, such as refund rate or latency. |
| **Winsorizing** | Capping extreme values at a chosen quantile so they don't dominate an average. |
| **Holm / Benjamini-Hochberg / Bonferroni** | Methods for adjusting p-values when many tests are run. |
| **Heterogeneity test** | A test of whether the effect truly differs between segments. |

---

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| Red message: "has N distinct values; pick the column holding the variant labels" | The Variant dropdown points at the wrong column. Pick the column holding the group labels (for example `test group`). |
| SRM fails on a dataset you know is fine | The test was designed with an unequal split. Tick **Intended split is not equal** and enter the shares. |
| Peeking, novelty, or bot checks show "skipped" | No timestamp column was selected, or there are fewer than 3 to 7 days of data. |
| CUPED not applied | No covariate chosen, or the covariate reduced variance by less than 1%. |
| Memo caption says "LLM unavailable" | No `GROQ_API_KEY`, a retired model name, or a network problem. Check `.env`, and see Groq's model list. The rule-based memo is shown meanwhile. |
| Memo caption says "LLM memo rejected" | The model wrote a number that was not in the computed results. The rule-based memo is used instead. This is the safeguard working. |
| "Analysis failed" message | A column type does not match the metric type (for example text chosen as a numeric metric). Re-check the mapping. |
| Changes to `.env` or code are ignored | Stop the app with `Ctrl+C` and run `python -m streamlit run app.py` again. |
