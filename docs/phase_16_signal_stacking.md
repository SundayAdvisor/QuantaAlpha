# Phase 16 — Signal stacking (Renaissance-style alpha combination)

Status: 📋 plan — Renaissance core principle. ~2-3 days for a real
implementation. Partly built today via QA's `combined_factors_df.parquet`
+ LightGBM, but worth being explicit about.

## What signal stacking is

Renaissance's documented edge is **signal stacking**: don't look for one
holy-grail factor, instead combine many weak, low-correlation signals
into a single composite. Each signal individually has a tiny IC (~0.02-0.05);
combined with low correlation between signals, the composite IC can reach
0.10-0.20 — the difference between "lucky" and "deployable."

The math is simple. If you have N signals each with IC = ρ and pairwise
correlation = c, the composite IC scales like:

```
IC_combined ≈ ρ × √(N / (1 + (N-1) × c))
```

So for ρ=0.05 (typical individual factor edge) with N=20 signals at
c=0.3 average pairwise correlation, the composite IC ≈ 0.16 — 3.2× the
individual signal. **The two levers are: more signals (N), and lower
correlation between them (c).**

## Where we are today

QA implicitly does signal stacking:
1. Mining produces 27-350 factor expressions over evolution rounds
2. `FactorAdmissionFilter` (corr ≤ 0.7, cap 50%) keeps a low-correlation
   subset (~30-50 factors)
3. `combined_factors_df.parquet` aggregates all admitted factor values
4. A LightGBM is trained on the full factor matrix → its predictions
   ARE the stacked signal
5. `predict_with_production_model.py` outputs the combined daily score

**This is signal stacking, just implicit and inflexible.** Specifically:

| What we have today | Limitation |
|---|---|
| LightGBM on all admitted factors | Black-box weights; hard to attribute alpha to individual signals |
| Single combiner (LightGBM only) | No comparison to simpler baselines (mean, IC-weighted, hierarchical) |
| Static admission threshold (0.7 corr) | Fixed; no decay-aware re-weighting |
| One model trained at extraction time | No online weight updates as live performance comes in |

Phase 16 makes this explicit + adds the missing pieces.

## What we'll build

### Layer A — Multiple combiners benchmarked side-by-side

Implement four combiners, score each on held-out data, pick the best
per regime:

```python
# quantaalpha/stacking/combiners.py

def equal_weight(signals: pd.DataFrame) -> pd.Series:
    """Mean of standardized signals. Simplest baseline."""
    return signals.apply(lambda s: (s - s.mean()) / s.std()).mean(axis=1)

def ic_weighted(signals, returns_forward, lookback=252):
    """Weight by trailing 1y IC. Higher-IC signals get more weight."""
    weights = signals.apply(lambda s: s.corr(returns_forward, lookback=lookback))
    weights = weights / weights.abs().sum()
    return (signals * weights).sum(axis=1)

def inverse_variance(signals):
    """Weight by 1/variance. Stable signals get more weight."""
    weights = 1.0 / signals.var()
    weights = weights / weights.sum()
    return (signals * weights).sum(axis=1)

def lightgbm_meta(signals_train, y_train, signals_predict):
    """What we have today. Nonlinear combiner."""
    import lightgbm as lgb
    model = lgb.LGBMRegressor(n_estimators=200, max_depth=4)
    model.fit(signals_train, y_train)
    return model.predict(signals_predict)

def hierarchical_risk_parity(signals):
    """Ledoit-Wolf shrunk covariance + recursive bisection for portfolio
    weights. From López de Prado MLAM ch. 4."""
    import riskfolio as rp
    port = rp.Portfolio(returns=signals)
    port.assets_stats(method_mu="hist", method_cov="ledoit")
    return port.optimization(model="HRP", rm="MV")
```

Five combiners. Each scored on:
- IC vs forward returns
- Sharpe of resulting portfolio
- Max drawdown
- Stability (rolling-window IC variance)

The winning combiner becomes the default for the Phase 5 bundle. Worst
case: equal-weight (the simplest baseline) wins, which is still informative
because it means our LightGBM isn't adding alpha over equal-weight.

### Layer B — Signal contribution attribution

For each admitted factor, compute its **marginal contribution** to the
combined signal's IC. This tells us:
- Which factors actually pull weight (deserve to be kept)
- Which factors are deadwood (could be dropped without losing edge)
- Where the alpha really comes from (interpretability)

```python
def marginal_ic_contribution(combiner, signals, returns_forward):
    """For each factor, compute IC_with - IC_without."""
    full_ic = ic(combiner(signals), returns_forward)
    contributions = {}
    for col in signals.columns:
        without = signals.drop(columns=[col])
        contributions[col] = full_ic - ic(combiner(without), returns_forward)
    return contributions
```

Output: a `bundle/contributions.json` showing each factor's marginal
contribution, sorted descending. Surface in the FE Models tab as a chart.

### Layer C — Regime-conditional stacking

Use Phase 15's HMM regime labels to fit **separate combiners per regime**:

```
combiner_state_0 = lightgbm.fit(signals[regime==0], returns[regime==0])
combiner_state_1 = lightgbm.fit(signals[regime==1], returns[regime==1])
combiner_state_2 = lightgbm.fit(signals[regime==2], returns[regime==2])

# At prediction time:
def predict_with_regime(signals, regime):
    return combiner_per_state[regime].predict(signals)
```

This captures the reality that different signals work in different
regimes. The strategy → regime matrix in Phase 15 gives the intuition;
Layer C operationalizes it with statistically-fit per-regime weights.

Caveat: per-regime fitting needs enough data per state. State 2
(turbulent) days are only ~10-15% of the calendar — at <500 days
that's getting thin for a LightGBM. Consider pooling or
shrinkage-toward-pooled.

### Layer D — Online weight refresh (the "continuous redevelopment" piece)

Renaissance's reported pattern: rebuild models every ~2 years.
Operationally:

1. Every N days (default 60), refit the combiner on the most recent K
   days (default 504 = 2yr) of admitted factors + realized returns
2. Compare new weights vs old via portfolio turnover (how much would
   positions change if we swapped combiners?)
3. If turnover > threshold, deploy new weights; else keep old (stability)
4. Track combiner-version history in `bundle/combiner_history.parquet`

This is a separate cron-style job, not a per-mining-run change. Spec
fits with Phase 9 (decay monitor) if/when that's built.

## How layers stack together

```
┌─────────────────────────────────────────────────────────┐
│ Phase 13 — admission gate (DSR + AST-novelty)           │
│   Produces: low-correlation factor pool (~30-50 factors)│
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 16 — signal stacking                              │
│                                                         │
│   Layer A: Try 5 combiners → pick best per metric       │
│   Layer B: Per-factor contribution attribution          │
│   Layer C: Regime-conditional fits (uses Phase 15)      │
│   Layer D: Online weight refresh every 60 days          │
│                                                         │
│   Output: combined daily signal (one number per ticker) │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 5/6 model bundle                                  │
│   ├─ model.lgbm — winning combiner saved                │
│   ├─ contributions.json — per-factor attribution        │
│   ├─ combiner_history.parquet — refresh log             │
│   └─ regime_combiners/ — per-regime variants if used    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              QC strategies via QAAlphaModel
```

## Build order within this phase

1. **Layer A — multiple combiners** (~1 day): write the 5 combiner
   functions, build a comparison harness (`scripts/compare_combiners.py`),
   run it on the existing baseline bundle to see which wins.
2. **Layer B — contribution attribution** (~half day): the marginal-IC
   loop + JSON output + FE display in Models page.
3. **Layer C — regime-conditional** (~half day, blocked on Phase 15):
   loop through regimes, fit combiner per state, validate.
4. **Layer D — online refresh** (~1 day, blocked on having ≥1 yr of
   continuous live data): cron + threshold logic.

Total standalone: 2-3 days. Layer C blocked on Phase 15 (HMM); layer D
blocked on accumulated live history.

## Validation

For each combiner:
- IC on held-out test segment (Phase 13's CPCV)
- Sharpe on TopkDropout backtest
- Compare to equal-weight baseline
- Stability: rolling 60-day IC standard deviation

Acceptance: at least one combiner shows ≥10% IC improvement over
equal-weight on held-out data. If equal-weight wins, ship that as the
default — it means we don't have enough alpha for the more complex
combiners to add value yet.

## Caveats

- **Don't over-engineer.** If you have 5 factors with IC=0.05 each and
  c=0.5 between them, the composite IC = 0.05 × √(5/3) ≈ 0.065. Layer A
  + B is sufficient. Skip C/D until you have ≥30 factors.
- **Watch for overfitting the combiner.** If your combiner has more
  parameters than your factor pool can support, it'll memorize the
  training-set noise. LightGBM with `max_depth=4, n_estimators=100` is
  conservative for this.
- **Equal-weight is hard to beat.** Most academic papers on signal
  combination show equal-weight + IR-weighted are within noise of
  each other; LightGBM rarely adds material edge over IR-weighted on
  noisy financial signals. Plan accordingly.

## File-level deliverables

```
quantaalpha/stacking/
  __init__.py
  combiners.py             # the 5 combiner functions
  attribution.py           # marginal IC contribution
  regime_conditional.py    # per-regime fitting (uses Phase 15)
  online_refresh.py        # cron-style weight rebuilder

scripts/
  compare_combiners.py     # CLI: take a bundle, run all 5 combiners,
                           # print + save score table
  refresh_combiner.py      # CLI for Layer D
```

## Cross-references

- [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md) —
  produces the low-correlation factor pool that this phase combines
- [phase_15_hmm_regime_layer.md](phase_15_hmm_regime_layer.md) — Layer C
  depends on regime labels
- [research_pipeline.md](research_pipeline.md) §Renaissance principles —
  signal stacking is the first row of the table
- López de Prado, *Machine Learning for Asset Managers* ch. 4
  (Hierarchical Risk Parity) — the HRP combiner
- The "1+(N-1)×c" formula: any portfolio theory text; standard result
