# 🧪 A/B Test Copilot

**Check whether an A/B test can be trusted before deciding whether to ship it.**

A/B Test Copilot takes raw experiment data and does three things most A/B tools skip. First, it audits whether the experiment was run correctly. Second, it analyzes the results with the right statistics. Third, it writes a plain-English ship / don't-ship memo with the risks, using only numbers the code computed.

> Dashboard walkthrough: see [`DASHBOARD.md`](DASHBOARD.md).

---

## Table of contents

1. [Project description](#project-description)
2. [Overview](#overview)
3. [Problem statement](#problem-statement)
4. [Features](#features)
5. [Tech stack](#tech-stack)
6. [Setup & usage](#setup--usage)
7. [Datasets](#datasets)
8. [Decision rules](#decision-rules)
9. [Project structure](#project-structure)
10. [Design decisions and limitations](#design-decisions-and-limitations)
11. [Testing](#testing)

---

## Project description

A/B Test Copilot is a Python analytics tool with a Streamlit dashboard. You upload a CSV of experiment data, map your columns, and get:

- a set of **health checks** that say whether the experiment was run correctly,
- a **statistical analysis** with confidence intervals, effect sizes and corrections,
- a **recommendation** (Ship / Don't ship / Keep running) with a trust level,
- a **stakeholder memo** written from verified numbers,
- an **exportable report** (Markdown or PDF).

Its main selling point is that it **catches bad experiments before they lead to bad decisions**. A result of "p < 0.05" is only meaningful if the experiment was valid, and this tool checks that first.

## Overview

```
raw CSV ─► health checks ─► statistics ─► decision rules ─► memo ─► dashboard / report
```

| Stage | What happens | Module |
|---|---|---|
| 1. Prepare | Clean the data (drop users seen in both arms, remove repeated rows) and run data-quality checks | `prep.py` |
| 2. Health | Sample ratio mismatch, peeking, novelty / primacy effects | `health.py` |
| 3. Statistics | Right test per metric type, confidence intervals, CUPED, power, multiple-comparison correction, segments | `stats.py` |
| 4. Decision | Apply rules to produce a recommendation and trust level | `decision.py` |
| 5. Memo | Groq writes the memo from pre-formatted facts; output is validated; a rule-based template is the fallback | `memo.py` |
| 6. Interface | Streamlit dashboard with Plotly charts and Markdown / PDF export | `app.py`, `charts.py`, `report.py` |

## Problem statement

Teams run A/B tests to make product decisions, but the decisions are often wrong for reasons that have nothing to do with the headline p-value:

- **The split was broken.** A bug drops users from one arm (sample ratio mismatch), so the groups are no longer comparable.
- **Someone peeked.** Checking results daily and stopping at the first significant result inflates false positives from 5% to 20% or more.
- **The lift was a novelty effect.** Users clicked a new button because it was new, and the effect faded.
- **The data was dirty.** Duplicate users, users in both groups, missing tracking data, and bot traffic all distort results.
- **Only the p-value was reported.** No confidence interval, no effect size, no power calculation, no correction for testing many metrics or segments.
- **Harm was hidden.** Conversion went up, but refunds went up too.

Most tools stop at "p < 0.05". A/B Test Copilot first asks whether the experiment deserves to be believed, then asks what the result means for the decision.

## Features

### 1. Experiment health checks
| Check | What it detects |
|---|---|
| **Sample ratio mismatch (SRM)** | The split between groups differs from what was intended (chi-square test) |
| **Peeking / early stopping** | Signs that the test was stopped at the first significant result, with the false-positive inflation this causes |
| **Novelty & primacy effects** | An effect that fades (novelty) or grows (primacy / learning) over the test |
| **Duplicate users** | Repeated user rows and users who appear in more than one variant |
| **Missing values** | High missing rates, including missingness that differs between arms |
| **Outliers** | Extreme values that can dominate a mean-based metric |
| **Bot-like traffic** | Abnormal bursts of traffic compared with the usual hour-of-day pattern |

### 2. Statistical analysis
- **Right test for the metric type:** two-proportion z-test (proportions), Welch t-test (means), delta-method z-test (ratios)
- **Confidence intervals and effect sizes** (Cohen's h / d), not just p-values
- **CUPED variance reduction** using a pre-experiment covariate, to detect smaller effects with less data
- **Power analysis and sample-size calculator**, including the smallest lift the current sample can detect and how many more days are needed
- **Multiple-comparison correction** across metrics and variants (Holm, Benjamini-Hochberg, or Bonferroni)
- **Segment breakdowns** (for example new vs returning, device, region) with a warning against cherry-picking and a heterogeneity test

### 3. Decision layer
- A **Ship / Don't ship / Keep running** recommendation with the reasoning
- A **trust level** (High / Medium / Low)
- **Guardrail checks**, for example conversion went up but refund rate also went up
- An **LLM-written memo** that can only use computed numbers (see below)

### 4. Interface
- Upload a CSV, map the columns, and get a dashboard with charts and the memo
- Export a **Markdown** or **PDF** report

### How the memo stays honest
The model never sees raw data and never chooses the recommendation. It receives a JSON of pre-formatted facts such as `"+5.23%"`. Every number in its output is matched against those facts (allowing for rounding). If any number is invented, the memo is rejected and replaced with a rule-based template. The memo also works with no API key at all.

## Tech stack

| Area | Tool |
|---|---|
| Language | Python 3.10+ |
| Statistics | SciPy, statsmodels |
| Data handling | pandas, NumPy |
| Visualization | Plotly |
| Dashboard | Streamlit |
| Output validation | Pydantic v2 |
| LLM memo | Groq API (default model `openai/gpt-oss-120b`, configurable) with a rule-based fallback |
| PDF export | fpdf2 |
| Config | python-dotenv |
| Testing | pytest |
| Data | Kaggle "Marketing A/B Testing" dataset plus synthetic experiments with planted flaws |

## Setup & usage

### Prerequisites
- Python 3.10 or newer
- (Optional) a Groq API key from [console.groq.com](https://console.groq.com) for LLM-written memos

### Install

```bash
# 1. Go to the project folder
cd ab-test-copilot

# 2. (Optional) create a virtual environment
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Mac / Linux

# 3. Install dependencies
python -m pip install -r requirements.txt
```

### Configure (optional)

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-120b
```

Without a key the app still works and writes the memo from the rule-based template. Groq retires models from time to time. If the memo shows an "LLM unavailable" note, check [Groq's model list](https://console.groq.com/docs/models) and update `GROQ_MODEL`.

### Run the dashboard

```bash
python -m streamlit run app.py
```

The app opens at `http://localhost:8501`. Stop it with `Ctrl+C`. Restart it after changing `.env` or any code.

### Try it in two minutes

1. In the sidebar keep **Synthetic demo** selected and pick a scenario (start with `srm` or `dirty_data`).
2. Click **Run analysis**.
3. Read the banner, then open the **Memo**, **Health checks**, **Results**, **Segments** and **Export** tabs.

### Synthetic scenarios

Each scenario has a deliberately planted flaw. The tool is not told what was planted.

| Scenario | Planted flaw | Expected outcome |
|---|---|---|
| `clean_win` | None, real +15% lift | SHIP |
| `clean_null` | None, no effect | DON'T SHIP |
| `srm` | Treatment silently drops ~8% of non-converting users | SRM fail, DON'T SHIP, low trust |
| `peeking` | No real effect, stopped the first day p < 0.05 | Peeking warning, KEEP RUNNING |
| `novelty` | Large early lift that decays | Novelty warning, KEEP RUNNING |
| `dirty_data` | Duplicates, users in both arms, differential missing data, bot burst | Several failed checks, low trust |
| `guardrail_breach` | Conversion up, refunds 2.5x | DON'T SHIP |

To write these to CSV files for testing the upload flow:

```bash
python scripts/generate_demo_data.py
```

## Datasets

### Kaggle: Marketing A/B Testing
Download `marketing_AB.csv` from <https://www.kaggle.com/datasets/faviovaz/marketing-ab-testing> (free Kaggle login required), unzip it, and place it in `data/`.

Upload it in the app with **Upload CSV** and map:

| Field | Value |
|---|---|
| User ID | `user id` |
| Variant / group | `test group` |
| Timestamp | `(none)` |
| Control label | `psa` |
| Treatment label | `ad` |
| Primary metric | `converted` (proportion) |
| Advanced → Intended split is not equal | `ad` = 0.96, `psa` = 0.04 |

The split step matters. The dataset is deliberately about 96% ad and 4% PSA, and without it the SRM check fails on perfectly valid data.

This dataset has no timestamps and no pre-experiment covariate, so the peeking, novelty, bot-traffic and CUPED features show as skipped. The synthetic scenarios cover them.

### Synthetic experiments
Generated by `ab_copilot/synthetic.py` with a fixed seed. They include a timestamp, a pre-experiment covariate (`pre_sessions`), guardrails (`refunded`, `revenue`) and segment columns (`device`, `user_type`, `country`).

## Decision rules

Implemented in `ab_copilot/decision.py`:

1. Any **failed health check** → **DON'T SHIP**, trust LOW ("fix and rerun").
2. Significant and **harmful** → **DON'T SHIP**.
3. Significant and good, but a **guardrail got worse** → **DON'T SHIP**.
4. Significant and good, but **peeking or novelty warnings** → **KEEP RUNNING**.
5. Significant and good with no blockers → **SHIP** (trust MEDIUM if other warnings exist).
6. Not significant and **underpowered** for your minimum worthwhile lift → **KEEP RUNNING** (with users and days still needed).
7. Not significant and **adequately powered** → **DON'T SHIP** (any real effect is smaller than the minimum worth detecting).

## Project structure

```
ab-test-copilot/
├── README.md                  project documentation (this file)
├── DASHBOARD.md               guide to every part of the dashboard
├── requirements.txt           dependencies
├── .env.example               optional Groq settings
├── app.py                     Streamlit dashboard
│
├── ab_copilot/                core package
│   ├── __init__.py
│   ├── schemas.py             Pydantic models: config, results, memo facts, memo
│   ├── utils.py               number formatting and memo number-grounding check
│   ├── prep.py                cleaning and data-quality checks
│   ├── health.py              SRM, peeking, novelty / primacy
│   ├── stats.py               tests, CUPED, power, corrections, segments
│   ├── decision.py            ship / don't ship rules
│   ├── pipeline.py            orchestration
│   ├── memo.py                Groq memo, validation, template fallback
│   ├── synthetic.py           scenarios with planted flaws
│   ├── report.py              Markdown and PDF export
│   └── charts.py              Plotly figures
│
├── tests/
│   └── test_core.py           13 tests
├── scripts/
│   └── generate_demo_data.py  writes synthetic CSVs to data/
└── data/                      put marketing_AB.csv here
```

## Design decisions and limitations

- **Peeking cannot be proven from data alone.** The check looks for signatures: ending within a day of first crossing the significance threshold, a p-value that crossed it repeatedly, or stopping short of the planned sample. The false-positive inflation figure comes from Armitage et al. (1969) and applies at alpha = 0.05 only. The check warns; it does not accuse.
- **Multiple testing.** Primary and secondary metrics across all variants are corrected together (Holm by default). Guardrails are deliberately not corrected, because missing real harm costs more than a false alarm.
- **CUPED** is applied when the covariate reduces variance by at least 1%. The covariate must be measured before the experiment.
- **SRM** runs after dropping users seen in both arms and repeated rows.
- **Novelty** compares the first and last third of the test, which is more powerful than a trend line over about 14 noisy days.
- **Ratio metrics** use the delta method. The peeking and novelty checks skip them.
- **Two-proportion test** uses unpooled standard errors, which matches the confidence interval.
- **Data layer:** pandas only. At this scale DuckDB or SQLite would add moving parts without benefit.
- **PDF export** is text only. Charts are in the dashboard.
- **Synthetic data** uses a fixed seed. On other seeds, a null scenario will occasionally show a false positive, which is what a real null test does.
- The LLM memo path depends on a model name that Groq may retire; the rule-based fallback keeps the app working.

### Possible extensions
Sequential testing (so peeking is allowed by design), Bayesian analysis, richer variance reduction beyond CUPED, and a SQL or DuckDB data connector for larger datasets.

## Testing

```bash
python -m pytest
```

13 tests cover each planted flaw (SRM, peeking, novelty, dirty data, guardrail breach), the clean win and clean null cases, CUPED, the sample-size calculation, ratio metrics, and the memo grounding check.
