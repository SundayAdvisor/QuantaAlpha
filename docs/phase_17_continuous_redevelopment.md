# Phase 17 — Continuous redevelopment (training cadence)

Status: 📋 plan + decision doc — answers the user's question "Renaissance
retrains every ~2 years; should we?". ~half-day implementation once the
strategy is decided.

## The question

Today's QA mining defaults: train **2008-01-02 → 2015-12-31** (8 years),
valid 2016 (1 yr), test **2017-01-03 → 2026-05-07** (~9.5 years).

Renaissance, per Zuckerman + the Acquired podcast, **rebuilds models
every ~2 years** because markets evolve. Two regime shifts visible in
SPY data alone since 2008:

| Regime era | Approximate years | What characterizes it |
|---|---|---|
| Post-GFC ZIRP recovery | 2009-2015 | Zero interest rates, slow grind up, "buy the dip" works |
| Late-cycle ZIRP | 2016-2019 | Rates start rising, sector dispersion increases |
| COVID + recovery + ZIRP again | 2020-2021 | Volatility regime shift, then meme-stock + AI flow |
| Rate-hike + bear + AI rally | 2022-2026 | Inflation normalization, dispersion explodes, AI mega-cap distortion |

**Our current train (2008-2015) covers ONLY the first era and the start
of the second.** It misses 2020 vol regime, 2022 bear, 2024 AI rally —
which is a problem for a model meant to deploy *today*.

## Three options, their tradeoffs

### A — Keep the current fixed split (default today)

| Pro | Con |
|---|---|
| Paper-comparable (matches QA paper splits) | Train data is stale — ZIRP-dominated era is over |
| Most data → most stable model fit | Doesn't capture current regime |
| Simple to reason about | Won't generalize to live deployment without re-validation |

**Use when**: benchmarking against the QA paper's reported numbers.
**Don't deploy live from this** without re-validation.

### B — Rolling N-year window (Renaissance-style, what I recommend)

Train on the most-recent N years; valid is N+1 quarter; test is the
remainder of available data. Refit periodically.

| Pro | Con |
|---|---|
| Captures current regime — matches what the model will see live | Less data → noisier fits |
| Forces continuous validation | More LLM tokens per refit |
| Replicates Renaissance's documented cadence | Loses paper-comparability |

Two practical sub-options:

- **B1 — Anchored expanding window**: train always starts 2008-01-02,
  test end advances. Trains on more data over time.
- **B2 — Rolling fixed-length window**: train is most-recent N years,
  starts also advance. Always-fresh training data.

Recommendation: **B2 with N=5 years, refit quarterly**. Specifically
right now:
- Train: **2018-01-01 → 2022-12-31** (5 yr)
- Valid: 2023 (1 yr)
- Test: **2024-01-01 → 2026-05-07** (~2.4 yr — short but recent)

This trains on the rate-hike + bear + AI-rally regime that's
operationally relevant for a model deployed in May 2026. The QA paper's
splits become a separate "paper-replication" preset.

### C — Walk-forward with multiple folds (gold standard, deferred)

K-fold rolling: each fold trains on N years, validates on next year,
tests on year after. Average across folds. Already documented as
[walk_forward_validation.md](walk_forward_validation.md) (Phase 10).

Deferred until Phase 13 lands (DSR/CPCV gate) — walk-forward without
proper CPCV leaks information.

## Concrete plan

### Step 17.1 — Add presets to FE Advanced panel

`ChatInput.tsx` Advanced panel currently shows 6 date pickers with paper-
aligned defaults. Add a preset dropdown:

```
Preset: [▼ Paper-aligned (2008-2015 / 2016 / 2017-2026)]
        ├ Paper-aligned (2008-2015 / 2016 / 2017-2026)         ← current default
        ├ Recent regime (2018-2022 / 2023 / 2024-2026)        ← B2 recommended
        ├ Stress test (2008-2018 / 2019 / 2020-2026)           ← survives COVID + bear
        ├ Walk-forward (will run multiple folds — slow)        ← Phase 10 gate
        └ Custom (date pickers below)
```

Each preset just sets the 6 date fields. Pickers remain editable for
custom.

### Step 17.2 — Add a "preset" tag to the manifest

Phase 6's `manifest.json` already records the segments. Add a top-level
field `training_preset` so we can group runs by preset for comparison
later:

```json
{
  "training_preset": "recent_regime",  // new
  "library_suffix": "...",
  "config": { ... }
}
```

### Step 17.3 — Periodic refit cron (Layer D-equivalent)

Every quarter (or N=60 trading days, configurable):

```
scripts/refit_quarterly.py:
  1. Run a fresh QA mining session with "Recent regime" preset
  2. Extract a Phase 5 bundle from the result
  3. Compare to the previous quarter's bundle:
     - IC on the new test window
     - Top-N factor turnover (how many factors changed)
     - Composite-signal correlation between old and new
  4. If ≥30% factor turnover OR IC drop, alert + flag for human review
  5. Otherwise auto-promote new bundle
```

Outputs `bundle/refit_log.jsonl` for traceability.

### Step 17.4 — A/B comparison harness

When both an old (paper-aligned) and new (recent-regime) bundle exist,
run their predictions on a common OOS window and compare:

```
scripts/compare_bundles.py --bundle-a smoke_test_baseline_v2 \
                           --bundle-b spy_recent_regime_v1 \
                           --start 2024-01-01 --end 2026-05-07
```

Output table:
- IC, RankICIR, IR per bundle
- Difference + p-value (paired t-test on daily IC)
- Visualize in FE Models page as "this bundle vs that bundle"

## What this means for our existing runs

The current 2026-05-08 mining run uses paper-aligned splits. The bundle
extracted from it (when you run Phase 9 smoke) will be tested on
2017-2020 in-sample (mining loop) + 2020-11-11 → 2026-05-07 OOS via
`predict_with_production_model.py`.

The OOS-only window (2020-11-11 → 2026-05-07) IS truly held out, so
the OOS metrics there are honest **regardless of training cadence**.
The question Phase 17 answers is: *"would a more recent training window
give a model that performs better on 2024-2026?"* That requires running
a second mining session with the "Recent regime" preset and comparing
via Step 17.4's harness.

## Recommendation

**Ship Step 17.1 (FE preset dropdown) immediately** — small effort,
unlocks running the comparison without needing custom date entry every
time.

**Then run two mining sessions back-to-back**:
1. Current run completes (paper-aligned, in progress)
2. Once done: kick off "Recent regime" preset run with same objective text
3. After both complete: run `compare_bundles.py` to see whether recent-
   regime training meaningfully helps on 2024-2026 OOS

If recent-regime wins by a clear margin: switch the FE default and
update [phase_7_universe_aware_mining.md](phase_7_universe_aware_mining.md)
to recommend recent-regime as default. If they're indistinguishable,
keep paper-aligned for benchmark-comparability + add recent-regime as
opt-in only.

**Skip Step 17.3 (cron refit) until you have ≥3 successful bundle
comparisons** — premature automation.

## File-level deliverables

```
frontend-v2/src/components/ChatInput.tsx
  - add preset dropdown in Advanced panel
  - 4 hardcoded presets + Custom

frontend-v2/backend/app.py
  - extend MiningStartRequest with training_preset: Optional[str]
  - record into manifest.json

scripts/
  compare_bundles.py        # Step 17.4 harness
  refit_quarterly.py        # Step 17.3 (deferred)

docs/
  phase_17_continuous_redevelopment.md   # this file
  phase_17_validation.md                 # write after running A/B
```

## Effort

- Step 17.1 (FE preset dropdown): 1 hour
- Step 17.2 (manifest field): 15 min
- Step 17.4 (compare_bundles.py): 2 hours
- Step 17.3 (refit cron): defer 1+ month — needs accumulated runs

Total active: ~half day.

## Caveats

- **More frequent refits ≠ better model.** If markets are noisy,
  retraining quarterly will inject estimation noise into the live
  signal. Default cadence should be longer (annual?) and only
  triggered by Phase 9 decay alerts.
- **Recent-only training risks regime collapse.** If you train only on
  2018-2022 and live data is 2026 with a *new* regime not seen in
  training, the model has no lever to handle it. Renaissance's edge
  is partly that they have so many models trained on different
  windows that some always cover current regime. We don't have that
  scale — so blend, don't fully replace.
- **Paper-aligned default is for comparison, not deployment.** Be very
  clear in the FE which preset is which: "Use paper-aligned to
  validate against the QA paper's reported numbers; use recent-regime
  for any real deployment consideration."

## Cross-references

- [research_pipeline.md](research_pipeline.md) §"Renaissance principles
  worth borrowing" — the "models reinvent every ~2 years" row
- [phase_7_universe_aware_mining.md](phase_7_universe_aware_mining.md) —
  current FE Advanced panel where presets get added
- [phase_16_signal_stacking.md](phase_16_signal_stacking.md) §Layer D —
  online weight refresh (parallel concept, separate mechanism)
- [walk_forward_validation.md](walk_forward_validation.md) — the K-fold
  alternative to Renaissance's two-year-cadence approach
