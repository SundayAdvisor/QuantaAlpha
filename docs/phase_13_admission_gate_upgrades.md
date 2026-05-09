# Phase 13 — Admission gate upgrades (statistical rigor)

Status: 📋 next — highest-ROI item in the research pipeline plan. ~1 day total.

The current factor admission gate (in `scripts/publish_findings.py`)
checks naive metrics: `RankICIR > 0.05`, `IR > 0`, `MaxDD > -40%`,
`top_n=5`. **This drastically overstates edge** because:

1. We mine many factors and pick the best — selection bias inflates Sharpe.
2. Walk-forward CV leaks information when label horizons overlap.
3. The factor pool collapses around similar mechanisms (we hit this around iter 11–12).

This phase adds 4 fixes from López de Prado's *Advances in Financial
Machine Learning* + AlphaAgent (arXiv 2502.16789):

| Fix | What it solves | Effort |
|---|---|---|
| **Deflated Sharpe Ratio (DSR)** | Selection bias when reporting best-of-N mined Sharpe | ~30 lines NumPy |
| **Combinatorial Purged CV (CPCV)** | Label-horizon overlap leaks across train/test boundaries | ~half day |
| **Triple-barrier labeling** | Better than fixed-horizon return labels — defines profit-take + stop + time-out | ~half day |
| **AST-similarity dedup** | Prevents factor pool collapse around one mechanism | ~half day |

## 1. Deflated Sharpe Ratio

**The problem.** If we mine 100 factors and report the highest Sharpe,
expected naive Sharpe is roughly `sqrt(2*ln(100)) ≈ 3.0` *under the null
hypothesis of zero true edge*. So a backtest Sharpe of 2.0 from
best-of-100 is *evidence against* edge, not for it.

**The fix.** DSR (Bailey & López de Prado, SSRN 2460551) deflates the
observed Sharpe by:
- Number of trials (selection bias)
- Skewness + kurtosis of returns (non-normality)
- Sample length (statistical confidence)

```python
# Sketch — full implementation ~30 lines
import numpy as np
from scipy.stats import norm

def deflated_sharpe_ratio(returns, n_trials, sr_benchmark=0.0):
    """
    Returns the probability that the observed SR is real (i.e., > sr_benchmark)
    after correcting for selection across n_trials.
    """
    sr = returns.mean() / returns.std() * np.sqrt(252)
    skew = returns.skew()
    kurt = returns.kurtosis()  # excess kurtosis
    T = len(returns)

    # Expected max SR under null (Bailey & LdP eq. 2)
    emc = 0.5772156649  # Euler-Mascheroni
    sr_n = (1 - emc) * norm.ppf(1 - 1.0/n_trials) + emc * norm.ppf(1 - 1.0/(n_trials * np.e))

    # Variance of SR estimator (eq. 7)
    var_sr = (1 - skew * sr + (kurt - 1) / 4 * sr**2) / (T - 1)
    psr = norm.cdf((sr - sr_n) / np.sqrt(var_sr))
    return psr  # probability that the SR > sr_n given the null
```

**Where to wire it:**
- New `quantaalpha/factors/admission/dsr.py`
- Add `min_dsr: float` (default 0.95 = 95% confidence) to
  `findings_config.json` gate
- `passes_gates()` in `publish_findings.py:136` adds DSR check

**Acceptance:** mining run with `n_trials = num_factors_mined` gates by
DSR. Naive-Sharpe winners that fail DSR (because they were lucky in N
trials) get rejected — visible in publisher output as
"`hypothesis_X: DSR=0.78 < 0.95 (failed selection bias check)`".

## 2. Combinatorial Purged Cross-Validation

**The problem.** When we predict 5-day forward returns and our train
ends 2015-12-31, the labels for the last 5 train days *use future info*
that overlaps with the valid set starting 2016-01-04. Standard
walk-forward CV ignores this and produces optimistic out-of-sample
metrics.

**The fix.** López de Prado's CPCV (*AFML* ch. 7):
- Slice the time index into K folds
- Form C(K, K-N) train/test combinations
- For each: **purge** observations whose labels overlap the test set;
  **embargo** a buffer after the test set to avoid leakage

```python
# Sketch using mlfinlab or DIY
from mlfinlab.cross_validation import CombinatorialPurgedKFold

cv = CombinatorialPurgedKFold(
    n_splits=10,            # K=10 folds
    n_test_splits=2,        # N=2 test folds per combination → 45 combos
    samples_info_sets=label_end_times,  # when each label "ends"
    pct_embargo=0.01,       # 1% post-test buffer
)
for train_idx, test_idx in cv.split(X):
    model.fit(X[train_idx], y[train_idx])
    score = model.score(X[test_idx], y[test_idx])
```

**Where to wire it:**
- New `quantaalpha/factors/admission/cpcv.py`
- Used in `extract_production_model.py` instead of qlib's default
  segments-based train/valid/test
- Optional: also during in-loop factor scoring (not just at extraction)

**Acceptance:** an `extraction_conf.yaml` produced via CPCV evaluates
the bundle on K-fold CPCV instead of single test segment. Reported
metric is the **mean across folds** (more conservative + honest).

## 3. Triple-barrier labeling

**The problem.** Fixed-horizon return labels (`y = price[t+5]/price[t] - 1`)
ignore that real strategies exit early on stops or take profits. A
factor that predicts the 5-day fixed return might fail when actual
trading uses risk controls.

**The fix.** Triple-barrier (*AFML* ch. 3) defines the label as
*whichever of three barriers hits first*:
- **Upper barrier** (profit target): `+2σ`
- **Lower barrier** (stop loss): `-2σ`
- **Time barrier** (max holding): 5 trading days

Label = `+1` (profit), `-1` (stop), or `0` (time-out near zero).

```python
# Sketch
import pandas as pd

def triple_barrier_labels(close, vol, t1, sigma_pt=2.0, sigma_sl=2.0):
    """
    close: pd.Series of prices indexed by date
    vol:   pd.Series of rolling realized vol (e.g., 20-day std)
    t1:    pd.Series — the time barrier per observation
    """
    out = pd.DataFrame(index=close.index, columns=["label", "ret"])
    for t0 in close.index:
        path = close.loc[t0:t1[t0]]
        upper = close[t0] * (1 + sigma_pt * vol[t0])
        lower = close[t0] * (1 - sigma_sl * vol[t0])
        hit_up = path[path >= upper].first_valid_index()
        hit_dn = path[path <= lower].first_valid_index()
        # First-touched barrier wins; else time-out at t1
        ...
    return out
```

**Where to wire it:**
- New `quantaalpha/factors/admission/triple_barrier.py`
- Optional label mode in `conf_baseline.yaml`:
  `label: triple_barrier(2.0, 2.0, 5)` instead of
  `Ref($close,-2)/Ref($close,-1) - 1`
- Cross-validate: compute triple-barrier labels alongside fixed-horizon,
  check IC of factor against both. If big divergence, the factor only
  works in idealized conditions.

**Acceptance:** at least one mining run uses triple-barrier as the label
function. Resulting factors selected by it should be more
risk-management-aware (less drawdown sensitivity).

## 4. AST-similarity deduplication (steal from AlphaAgent)

**The problem.** Mining converges on similar factor expressions around
iter 11–12 — visible in our paper-replication runs where the pool
admits ~350 factors but most are momentum or volatility variants of
each other. The mutation/crossover loop reinforces a single mechanism
once it's working.

**The fix.** AlphaAgent's AST-novelty regularizer (arXiv 2502.16789):
- Parse each factor expression into an Abstract Syntax Tree
- Compute structural similarity vs all already-admitted factors
- Reject candidates whose max-similarity exceeds a threshold

```python
# Sketch
def ast_similarity(expr_a: str, expr_b: str) -> float:
    """Tree-edit distance normalized to [0,1]."""
    ast_a = parse_qlib_expr(expr_a)
    ast_b = parse_qlib_expr(expr_b)
    return 1.0 - tree_edit_distance(ast_a, ast_b) / max(size(ast_a), size(ast_b))

def passes_novelty_gate(candidate_expr, admitted_exprs, max_sim=0.7):
    if not admitted_exprs:
        return True
    sims = [ast_similarity(candidate_expr, e) for e in admitted_exprs]
    return max(sims) < max_sim
```

**Where to wire it:**
- New `quantaalpha/factors/admission/ast_novelty.py`
- Hook into `FactorAdmissionFilter` in `quantaalpha/factors/runner.py:149`
  (where corr-threshold dedup already runs — add AST similarity as a
  pre-filter)
- Tunable: `ast_similarity_max` in `findings_config.json`

**Acceptance:** mining run produces a factor pool with diverse mechanisms.
Visualize via 2D PCA / UMAP on AST embeddings — should see clusters
across momentum/volatility/cross-sectional/etc., not all in one corner.

## Build order within this phase

1. **DSR first** (~2 hours) — biggest selection-bias correction, smallest code
2. **AST-novelty next** (~3 hours) — directly addresses the iter-11-12 mode collapse we observe
3. **CPCV** (~half day) — bigger lift, requires changing the qlib-config segment loader
4. **Triple-barrier** (~half day) — optional/optional, compare alongside fixed-horizon

Total: ~1.5 days of focused work.

## File-level deliverables

```
quantaalpha/factors/admission/
  __init__.py
  dsr.py           # Deflated Sharpe Ratio
  cpcv.py          # Combinatorial Purged Cross-Validation
  triple_barrier.py
  ast_novelty.py   # AST similarity dedup

scripts/publish_findings.py
  - extend gate config with min_dsr, ast_similarity_max
  - call admission/* in passes_gates()

quantaalpha/factors/runner.py
  - hook ast_novelty into FactorAdmissionFilter

extract_production_model.py
  - optional CPCV mode for bundle extraction
```

## Cross-references

- López de Prado, *Advances in Financial Machine Learning* (2018), ch. 3, 4, 7, 14
- Bailey & López de Prado, "The Deflated Sharpe Ratio" (SSRN 2460551, 2014)
- AlphaAgent, "LLM-Driven Alpha Mining with Regularized Exploration" (arXiv 2502.16789)
- Roadmap row: ★ Full research pipeline → [research_pipeline.md](research_pipeline.md)
