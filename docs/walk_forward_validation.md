# Walk-Forward Validation (QA, planned — not built)

Status: 📋 sketch — analogous to QuantaQC's Phase 8. Captures the plan so
it isn't lost. Not scheduled; build when in-sample bias becomes a real
problem in deployment.

## Why this matters for QA

Today QA's mining loop:

1. Trains a LightGBM on the **train segment** (default 2008-01-02 → 2015-12-31)
2. Early-stops on the **valid segment** (2016)
3. Computes IC / RankICIR / IR / MaxDD on the **test segment** (2017-01-03 → user-set test_end)
4. **Uses those test-segment metrics to pick parents** for mutation/crossover

Step 4 is the leak. Test data drives factor selection across iterations,
even though the GBT itself never saw it. After 5 evolution rounds across
N parallel directions, the surviving factors are biased toward whatever
worked on that specific test window.

The paper sidesteps this with cross-market transfer (§5.4): mine on CSI
300, deploy on CSI 500 / S&P 500 with no re-fit. That's a strong test —
but it's a separate manual step, not part of the mining loop itself.

## Vocabulary

- **Train fold** — fits the per-iteration LightGBM. Same as today.
- **Valid fold** — early-stopping + hyperparameter selection. Same as today.
- **In-loop test fold** — drives mutation/crossover parent selection. **Today this is the test segment; under walk-forward it would be a held-in window inside an outer-loop split.**
- **Holdout window** — never seen by the mining loop. Final report-only.

## 3 design options (pick one when building)

### A. Single anchored split + holdout (smallest change)

Today: train / valid / test
After: train / valid / **in-loop-test** / **holdout**

- Train 2008–2015 (8 yr) — fits GBT
- Valid 2016 (1 yr) — early stop
- In-loop test 2017–2022 (6 yr) — drives parent selection
- Holdout 2023–today (~3+ yr) — never seen during mining; report-only after run completes

Pro: one extra metric to compute per iteration; no architecture change to
the loop itself. Cheap.

Con: still a fixed split; doesn't capture regime drift.

### B. K-fold rolling walk-forward (gold standard)

Slice the test region into K rolling folds:

```
fold 1:  train 2008-13 / valid 2014 / in-loop-test 2015
fold 2:  train 2009-14 / valid 2015 / in-loop-test 2016
fold 3:  train 2010-15 / valid 2016 / in-loop-test 2017
...
fold 9:  train 2016-21 / valid 2022 / in-loop-test 2023
```

For each candidate factor: run all K folds, average the in-loop-test
RankICIR. Selection metric becomes the K-fold mean.

Pro: directly tests robustness across regimes. The metric is closer to
"what to expect live."

Con: K× more compute per iteration. Even at K=4, each iteration is
4× slower. Worth it for high-stakes runs, overkill for exploration.

### C. Anchored expanding window (compromise)

Train grows over time:

```
fold 1: train 2008-2014 → in-loop-test 2015
fold 2: train 2008-2015 → in-loop-test 2016
fold 3: train 2008-2016 → in-loop-test 2017
...
```

Pro: more stable than B (more data per fit); captures regime drift better
than A.

Con: 2× compute typically; later folds overfit to recent regime.

**Recommendation when we build it: ship A first (single anchored + holdout) — cheapest, biggest in-sample-bias reduction per dollar of work. B/C are upgrades.**

## Score combinations to consider

When you have train + in-loop-test scores, how to combine them:

| Mode | Formula | Punishes |
|---|---|---|
| Validation only | `score = val_RankICIR` | Nothing — same as today |
| Penalized divergence | `score = val_RankICIR - 0.5 * |val - train|` | Curve-fits (train≫val) |
| Min-of-folds | `score = min(fold_RankICIR for fold in folds)` | One-regime wonders |
| Geometric mean | `score = (prod(folds))^(1/K)` | Heavy losses in any fold |

For QA, **penalized divergence** is the sensible default — it directly
targets the curve-fit-smell case (positive RankICIR but negative IR =
"regime-fit" verdict in our AI verdict taxonomy).

## Architecture changes (when building Option A)

Today (concept):
```python
# In each evolution round
for candidate in candidates:
    metrics = backtest(factor, segments=conf_baseline.segments)   # train/valid/test
    candidate.score = metrics["RankICIR"]                         # test-segment
```

Option A:
```python
# Slice off a portion of test → holdout. Mining only sees in_loop_test.
inner_segments = {
    "train":         segments["train"],
    "valid":         segments["valid"],
    "test":          segments["in_loop_test"],   # ends earlier
}
metrics = backtest(factor, segments=inner_segments)
candidate.score = metrics["RankICIR"]

# After mining completes, run holdout once on the admitted pool only.
# This produces a separate "holdout_RankICIR" per factor.
```

The qlib config already supports custom segments (we wired this up in the
universe-aware-mining work). Adding a 4th segment requires a small change
to `factor_template/conf_baseline.yaml` schema, the workspace-override
patch in `frontend-v2/backend/app.py:_run_mining`, and a new endpoint
`POST /api/v1/runs/{run_id}/holdout-eval` that reruns predict on the
held-out range using the run's bundle.

## Estimated effort

- Option A (single split + holdout): ~3–5 hours
- Option B (K-fold rolling): ~1–2 days (parallelism + tooling)
- Option C (expanding): ~1 day

## When to actually build this

Trigger conditions:

1. We've successfully extracted a factor-trained bundle (Phase 5/6 ran end-to-end on real data) AND
2. That bundle's holdout-window RankICIR (validated via `predict_with_production_model.py`) is materially worse than the in-loop test RankICIR — i.e. we have empirical evidence the loop is overfitting AND
3. We're considering deploying a factor and need confidence the metric is honest

If all three are true, Option A is worth doing immediately. Otherwise it's
a nice-to-have.

## Cross-references

- QA's existing in-sample-bias note: [phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md)
- QA paper §5.4 cross-market transfer (the paper's substitute for walk-forward)
- QC's analog: [QuantaQC/docs/phase_8_walk_forward_evolution.md](../../QuantaQC/docs/phase_8_walk_forward_evolution.md)
- QA's home-page info panel that flags this issue to the user (yellow warning bullet)
