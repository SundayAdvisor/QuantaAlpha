# Phase 9 — End-to-end smoke run

Status: 📋 next — the highest-value validation step. ~1–3 hours (mostly waiting).

The whole pipeline (phases 1–7) hasn't been exercised end-to-end with a
real factor-trained bundle yet. Both existing bundles
(`smoke_test_baseline`, `smoke_test_baseline_v2`) have
`num_factors_in_metadata: 0` — they were trained on the 20 Alpha158
features only, with `test_rank_ic ≈ 0.005` (noise level).

This phase produces the first bundle that actually contains QA's mined
alpha, then validates it on truly held-out data.

## Why this is critical

Until phase 9 runs:
- We don't know whether the universe-aware mining override (phase 7)
  actually works at the qlib data-loader level
- We don't know whether `extract_production_model.py` produces something
  meaningfully better than baseline
- The paper's S&P 500 transfer claim (~137% excess return over 4 years)
  is unsubstantiated in our setup
- Phase 11 (QC integration) has nothing real to consume

It's the linchpin.

## Step-by-step

### Step 1 — Pick the input

Use either:
- An existing finished mining run (e.g. `2026-05-08_02-13-32-…` — best
  RankICIR 0.0706 — already on disk), OR
- A fresh mining run via the Advanced panel (recommended: pick
  current-regime split, e.g. train 2014-2021, valid 2022, test 2023-2026)

### Step 2 — Extract the bundle

Models tab → Build new → pick the workspace from step 1 → bundle name
something like `spy_v1_factor_trained_<date>` → click Build.

Alternative CLI:
```bash
.venv/Scripts/python.exe extract_production_model.py \
  --workspace data/results/workspace_exp_<...> \
  --output-name spy_v1_factor_trained
```

Expected output:
- `data/results/production_models/spy_v1_factor_trained/`
- `metadata.json` should show `num_factors_in_metadata > 0`
- `test_rank_ic` should be **materially > 0.005** (the baseline)

If `num_factors > 0` but `test_rank_ic` is still ~0, the mined factors
aren't predictive. Stop and analyze.

### Step 3 — Predict on held-out OOS

```bash
.venv/Scripts/python.exe predict_with_production_model.py \
  --bundle data/results/production_models/spy_v1_factor_trained/ \
  --start 2020-11-11 \
  --end   2026-05-07 \
  --output predictions/spy_v1_oos.csv
```

This is the genuine OOS test — none of those dates were seen during
mining (the run's test segment was 2017-2020-11-04 for the existing
2026-05-08 run, or whatever the user picked).

### Step 4 — Compare metrics

Compute on the predictions CSV:
- IC = pearson(score, next-day return)
- Rank IC = spearman(score, next-day return)
- IR = mean(daily long-short returns) / std × √252

If IC / Rank IC are within ~50% of the in-sample test metrics, the
factor generalizes. If they collapse to near-zero or flip sign, it was
curve-fit. Either outcome is informative.

A small helper script will be needed:
```bash
scripts/score_predictions.py --predictions predictions/spy_v1_oos.csv
```

### Step 5 — Document the outcome

Write findings to `docs/phase_9_validation.md` with:
- Bundle name + source workspace
- In-sample metrics (from `metadata.json`)
- OOS metrics (from step 4)
- Verdict: generalizes / curve-fit / regime-fit / inconclusive
- Recommendation: whether to ship to phase 11 (QC integration)

## Acceptance

- A bundle exists with `num_factors_in_metadata > 0` AND `test_rank_ic > 0.04`
- A predictions CSV exists for 2020-11-11 → 2026-05-07
- A docs/phase_9_validation.md exists with the comparison

## What this unlocks

- Phase 10 (walk-forward) becomes evaluable: do we actually need walk-
  forward, or did our mined factors generalize fine?
- Phase 11 (QC integration) becomes meaningful: we have a real bundle
  to feed into a QAAlphaModel
- Future runs have a baseline to beat

## Why I haven't done this yet

It costs LLM tokens + wall time. The user (you) is the right person to
kick it off because you control the spend. Once you click "Build" in
Models > Build new, the rest is mechanical.

## Cross-references

- Prerequisite: a finished mining workspace exists. See [experiment_guide.md](experiment_guide.md) for how to start one.
- Bundle layout: [phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md)
- After this phase: [walk_forward_validation.md](walk_forward_validation.md), [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md)
