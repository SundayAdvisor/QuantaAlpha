# Phase 15 — HMM regime detection + strategy mapping

Status: 📋 next-up — Renaissance-flavored. ~half day for the regime
detector itself; another half day for strategy-gate integration.

The single most "Renaissance-flavored" addition we can make to the stack
with realistic effort. Hidden Markov Models infer **unobserved market
regimes** (calm / normal / turbulent) from observable returns + vol.
Different strategies work in different regimes — without regime
awareness, a backtest averages performance across all regimes and we
miss that a Sharpe-1.0 factor is actually Sharpe-2.5 in calm regimes
and Sharpe-(-0.5) in turbulent ones.

## Why this matters (short version)

Robert Mercer + Peter Brown brought Baum-Welch / HMM from IBM Watson
speech-recognition to Renaissance in 1993. The intuition: if HMMs decode
phonemes from noisy acoustics, they decode regimes from noisy returns.
The math is identical, only the application changed. The regime layer
gives the rest of the stack a tool that's not in qlib's default operator
library and that the QA paper handles only implicitly via "regime-conditioned"
factor mechanism.

## What "regime" means concretely

A 3-state HMM trained on (daily SPY return, 5-day rolling realized vol)
typically segments market history like:

| State | Profile | Where it fires (SPY 2017-2026) |
|---|---|---|
| **0 — calm bull** | low vol (~10-15% ann), small positive drift | most of 2017, parts of 2019, 2021 melt-up, late 2024 AI rally |
| **1 — normal** | medium vol (~15-20%), mixed direction | bulk of 2018-2020, much of 2023 |
| **2 — turbulent** | high vol (>25%), large daily swings | Feb 2018 Volmageddon, Oct-Dec 2018, **Mar 2020 COVID**, 2022 bear lows, Mar 2023 banking crisis |

State 2 days are a small fraction (~10-15% of the calendar) but
disproportionately drive losses in trend-following strategies and gains
in mean-reversion/short-vol strategies.

## Strategy → regime mapping (the practical matrix)

This is the table you'd actually use to gate strategies by regime:

| Strategy family | State 0 (calm) | State 1 (normal) | State 2 (turbulent) |
|---|---|---|---|
| **Trend-following / Momentum** | ✅ best regime — slow trends, low whipsaw | ⚠️ mixed — choppy days | ❌ blows up — whipsaw + sharp reversals |
| **Mean-reversion / Reversal** | ⚠️ small wins (low dispersion to revert) | ✅ steady wins | ✅ pays off (oversold bounces, overbought peaks) |
| **Cross-sectional factors (value, quality)** | ✅ steady alpha | ✅ steady alpha | ⚠️ factor returns spike-correlate with market in crashes (drawdowns concentrate) |
| **Vol-selling / Short straddles** | ✅ collects premium efficiently | ⚠️ premium worth less than risk | ❌ catastrophic (Feb 2018, Mar 2020) — historical blowups happen here |
| **Long-vol / VIX call buying** | ❌ premium decays | ⚠️ negative carry | ✅ massive payoff |
| **Cash / inverse-vol allocation** | ❌ opportunity cost | ⚠️ underperforms | ✅ best risk-adjusted return |
| **Pairs / cointegration** | ⚠️ tight spreads, less profit | ✅ normal spread oscillation | ⚠️ correlations break down → wider spreads / blowouts |

Two ways to use this:

### Use 1 — As an input feature to factor mining

Add `$regime` to qlib's available custom features. The LLM in QA's
planner gets told: *"You can use `$regime` (0=calm, 1=normal, 2=turbulent)
in your factor expressions and as a gate."*

Example LLM-generated factor expression that uses it:
```
WHERE($regime != 2,
      ZSCORE(-TS_PCTCHANGE($close, 5)),
      0)
```
"5-day reversal, but zero exposure during turbulent regime."

### Use 2 — As a strategy-level gate at execution

In QC, the strategy class gets a `qa_regime[date]` lookup (similar to
how Phase 11's QAAlphaModel is planned). Position sizing scales by
regime:

```python
# Inside the QC strategy
if regime == 0:    weight = 1.0     # calm: full size
elif regime == 1:  weight = 0.7     # normal: scale back
else:              weight = 0.0     # turbulent: sit out
```

Or smoother: `weight = 1.0 - 0.5 * regime_2_probability` for continuous
scaling rather than hard cutoffs.

## Implementation

### Step 15.1 — Regime detector (core)

```python
# quantaalpha/regimes/hmm_regime.py
from hmmlearn import hmm
import numpy as np
import pandas as pd
from pathlib import Path

def fit_hmm_regime(
    returns: pd.Series,           # daily SPY returns
    rolling_vol: pd.Series,       # 5-day annualized vol
    n_states: int = 3,
    seed: int = 42,
) -> tuple[np.ndarray, hmm.GaussianHMM]:
    """Fit Gaussian HMM. Returns state sequence + fitted model."""
    features = np.column_stack([returns.values, rolling_vol.values])
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=200,
        random_state=seed,
    )
    model.fit(features)
    states = model.predict(features)
    return states, model

def label_regimes_by_vol(
    states: np.ndarray, rolling_vol: pd.Series
) -> dict[int, str]:
    """Sort states by mean rolling-vol so state 0 = calm, 2 = turbulent."""
    means = {s: rolling_vol.values[states == s].mean() for s in np.unique(states)}
    sorted_states = sorted(means, key=means.get)
    return {old: new for new, old in enumerate(sorted_states)}
```

### Step 15.2 — Pre-compute regime as a qlib feature

For each ticker (or just SPY for index-wide regime), pre-compute the
regime label per day → write a parquet that qlib's `StaticDataLoader`
can read:

```
data/qlib/us_data/regimes/
  spy_3state_hmm_v1.parquet     # date | state | p_state_0 | p_state_1 | p_state_2
```

Then expose to qlib via a `StaticDataLoader` entry referencing
`$regime`, `$p_calm`, `$p_normal`, `$p_turbulent` per day (broadcast to
all tickers in the universe — regime is index-wide, not per-ticker).

### Step 15.3 — Wire `$regime` into the mining loop

Two changes:
- `quantaalpha/factors/factor_template/conf_baseline.yaml`: add the
  regime feature loader so qlib serves `$regime` to factor expressions
- `quantaalpha/pipeline/prompts/planning_prompts.yaml`: add a paragraph
  to the LLM system prompt explaining the regime feature is available
  and what each state means

### Step 15.4 — QC strategy gate

When Phase 11 builds `QAAlphaModel`, also load the regime parquet so
strategies can do `weight = regime_to_weight(regime[t])`.

## Validation plan

1. **Train the HMM on SPY 2017-2020-11-04** (matches the original test
   segment of QA's bundles), inspect the state sequence on chart.
2. **Apply to 2020-11-11 → 2026-05-07** (truly held-out OOS that nothing
   else in the stack has seen during mining). Verify:
   - Mar 2020 → state 2
   - Dec 2020 onward → states 0/1
   - 2022 bear → mostly state 1, occasional state 2 spikes
   - 2024 AI rally → predominantly state 0
3. **Statistical sanity**: average return + vol per state (should
   monotonically separate); transition probabilities ≥ 80% same-state
   (regimes should be persistent, not flickering).
4. **Strategy comparison**: take an existing QA bundle's predictions,
   run two TopkDropout backtests: ungated, vs gated with `weight=0`
   in state 2. Should improve Sharpe materially if the gate is real.

## Caveats

- **HMM is unsupervised** — the states it finds aren't guaranteed to
  match human "calm/turbulent" intuition. Look at the per-state vol +
  return averages to confirm they sort sensibly. If two states look
  similar, drop to 2-state model.
- **Look-ahead bias risk** — if you fit the HMM on 2008-2026 data and
  apply labels back to 2008, you've leaked future info. Fit only on
  pre-2017 data, label 2017+ via Viterbi (one-step decode), or use a
  rolling-window fit.
- **Regime regimes change too** — "what calm looks like" in 2008-2015
  ZIRP era ≠ post-2022 rate-hike regime. Plan to refit annually.

## File-level deliverables

```
quantaalpha/regimes/
  __init__.py
  hmm_regime.py           # fit_hmm_regime + label_regimes_by_vol
  precompute.py           # CLI: writes regimes/<name>.parquet

scripts/
  fit_regimes.py          # one-shot script — fit + write parquet
                          #   args: --start 2017-01-01 --end 2020-11-10
                          #         --states 3 --output spy_3state_hmm_v1

quantaalpha/factors/factor_template/
  conf_baseline.yaml      # add regime parquet to data_loader_l
  conf_combined_factors.yaml  # same

quantaalpha/pipeline/prompts/
  planning_prompts.yaml   # mention $regime is available

docs/
  phase_15_hmm_regime_layer.md   # this file
  phase_15_validation.md         # write after running step-by-step validation
```

## Effort

- Step 15.1 (detector + script): 2 hours
- Step 15.2 (parquet + qlib wiring): 2 hours
- Step 15.3 (prompt update): 30 min
- Step 15.4 (QC gate): 1 hour (when Phase 11 is built)
- Validation per the plan above: 1-2 hours

Total: ~half day standalone, plus the QC integration when Phase 11 lands.

## Cross-references

- [research_pipeline.md](research_pipeline.md) §"Renaissance principles
  worth borrowing" — the HMM row
- [phase_16_signal_stacking.md](phase_16_signal_stacking.md) — how the
  regime feeds into the alpha combiner (gate or feature)
- López de Prado, *Advances in Financial Machine Learning* ch. 17
  (structural breaks) — alternative regime detection methods (CUSUM,
  Bai-Perron tests) worth knowing
- Renaissance Technologies background: Zuckerman, *The Man Who Solved
  the Market* (2019); Acquired podcast March 2024 episode
