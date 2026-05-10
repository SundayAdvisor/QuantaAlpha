# Math-Heavy Methods Worth Knowing for Quant Research

Status: 📚 reference doc — not a build phase.

A practical survey of mathematical methods that quant firms (Renaissance,
AQR, Two Sigma) use and that are directly applicable to an LLM-driven
factor-mining stack. For each: intuition (no notation overload), where
it shows up in real quant work, library + code sketch, how it could be
incorporated into QA, and reading.

This is reading material, not a build commitment. Pick what's relevant
to whatever phase you're working on; many entries are cross-referenced
to specific phase docs.

---

## 1. Statistical-significance methods

The biggest blind spot in factor mining: mining lots of factors and
reporting the best, without correcting for selection bias. Without
these methods, your reported metrics overstate edge by a factor of
2-5×.

### 1.1 Deflated Sharpe Ratio (DSR)

Naive Sharpe = `mean(returns) / std(returns) × √252`. If you mine 100
factors and report the best, expected naive Sharpe under the *null
hypothesis of zero true edge* is roughly `√(2 × ln(100)) ≈ 3.0`. So a
backtest Sharpe of 2.0 from best-of-100 is *evidence against* edge,
not for it.

DSR (Bailey & López de Prado 2014, SSRN 2460551) deflates the observed
Sharpe by:
- Number of trials (selection bias)
- Skewness + kurtosis of returns (non-normality)
- Sample length

Output: a probability that the "true" Sharpe exceeds zero.

```python
import numpy as np
from scipy.stats import norm

def deflated_sharpe_ratio(returns, n_trials, sr_benchmark=0.0):
    sr = returns.mean() / returns.std() * np.sqrt(252)
    skew, kurt = returns.skew(), returns.kurtosis()  # excess kurt
    T = len(returns)
    emc = 0.5772156649  # Euler-Mascheroni
    sr_n = (1 - emc) * norm.ppf(1 - 1.0/n_trials) + emc * norm.ppf(1 - 1.0/(n_trials * np.e))
    var_sr = (1 - skew * sr + (kurt - 1)/4 * sr**2) / (T - 1)
    psr = norm.cdf((sr - sr_n) / np.sqrt(var_sr))
    return psr  # probability sr > sr_n given the null
```

**For QA**: gate published factors by DSR > 0.95 (95% confidence).
Naive-Sharpe winners that fail DSR get rejected. Spec: [phase_13](phase_13_admission_gate_upgrades.md).

**Read**: López de Prado, *Advances in Financial Machine Learning* (AFML),
ch. 14. Bailey & LdP, "The Deflated Sharpe Ratio" (SSRN 2460551, 2014).

### 1.2 Multiple-testing correction

Even if each individual factor's p-value is < 0.05, mining 100 factors
guarantees ~5 false positives. Correct via:
- **Bonferroni**: divide α by N (conservative)
- **Benjamini-Hochberg**: control false-discovery rate (less conservative,
  more standard in finance research)

```python
from statsmodels.stats.multitest import multipletests
reject, p_corrected, _, _ = multipletests(
    pvalues, alpha=0.05, method='fdr_bh'
)
```

**For QA**: report both raw and corrected p-values per published factor.

### 1.3 Combinatorial Purged Cross-Validation (CPCV)

Walk-forward CV is the standard for time-series, but it leaks
information when label horizons overlap. If your label is 5-day forward
return, the last 5 train days share information with the first 5 valid
days.

CPCV's fix: **purge** observations whose labels overlap the test set;
**embargo** a buffer after the test set. Combinatorial: try multiple
test-fold combinations and average.

```python
from mlfinlab.cross_validation import CombinatorialPurgedKFold
cv = CombinatorialPurgedKFold(
    n_splits=10, n_test_splits=2,
    samples_info_sets=label_end_times,
    pct_embargo=0.01,
)
```

**For QA**: replace qlib's default segment-based CV with CPCV in
`extract_production_model.py`. Spec: [phase_13](phase_13_admission_gate_upgrades.md).

**Read**: AFML ch. 7.

---

## 2. Time-series structure methods

These detect non-iid structure that financial returns actually have:
regime switches, cointegration, autocorrelation, time-varying volatility.

### 2.1 Hidden Markov Models (HMM)

Returns + vol come from an *unobserved regime* that controls their
distribution. HMM infers the regime sequence via Baum-Welch (EM
algorithm). Renaissance famously brought this from IBM Watson speech
recognition in 1993.

```python
from hmmlearn import hmm
features = np.column_stack([returns, rolling_vol])
model = hmm.GaussianHMM(n_components=3, covariance_type="diag")
model.fit(features)
states = model.predict(features)  # 0/1/2 per day = regime label
```

**For QA**: use as a `$regime` qlib feature for factor expressions, or
as a strategy-execution gate. Spec: [phase_15](phase_15_hmm_regime_layer.md).

**Read**: Bishop, *Pattern Recognition and Machine Learning* ch. 13.
Acquired podcast March 2024 episode on Renaissance.

### 2.2 Kalman filter (online state estimation)

Estimates an unobserved state from noisy observations, updates online
as new data arrives. Used in pairs trading for time-varying hedge
ratios; in factor research for online beta updates.

```python
from filterpy.kalman import KalmanFilter
kf = KalmanFilter(dim_x=2, dim_z=1)
# Set up state-transition matrix, observation matrix, noise covariances
# Then iterate:
for z in observations:
    kf.predict()
    kf.update(z)
    # kf.x is the current state estimate
```

**For QA**: dynamic factor weights (combine with phase 16's signal
stacking for time-varying weights instead of static fitted weights).
For QC: dynamic hedge ratios in pairs strategies.

**Read**: Welch & Bishop, "An Introduction to the Kalman Filter"
(free PDF online).

### 2.3 Cointegration / Johansen test

Two time series can each be non-stationary (random walk) but their
linear combination stationary — cointegrated. The classic stat-arb
setup: long one stock, short another in fixed proportion → spread
mean-reverts.

- **Engle-Granger** (two-step): for pairs only
- **Johansen** (VECM): for baskets of N > 2 assets, also identifies
  the cointegrating rank

```python
from statsmodels.tsa.vector_ar.vecm import coint_johansen
result = coint_johansen(prices_df, det_order=0, k_ar_diff=1)
# result.lr1 = trace statistic; compare to critical values
# result.evec = cointegrating vectors (the linear combinations)
```

**For QA**: not directly applicable to cross-sectional factor mining
(QA's setup ranks stocks; cointegration is bilateral). But for a
future "stat-arb scanner" that screens SP500 pairs for cointegrated
spreads, this is the standard tool.

**Read**: Hamilton, *Time Series Analysis* (1994), ch. 19. Stefan
Jansen's repo notebook `09_time_series_models/05_cointegration_tests.ipynb`.

### 2.4 GARCH for volatility forecasting

Returns are nearly uncorrelated, but **squared returns have strong
serial correlation** — high vol days cluster ("volatility clustering").
GARCH (Generalized AutoRegressive Conditional Heteroskedasticity)
models this directly. Useful for vol-targeted position sizing.

```python
from arch import arch_model
am = arch_model(returns * 100, vol='GARCH', p=1, q=1)  # GARCH(1,1)
res = am.fit(disp='off')
forecast_vol = res.forecast(horizon=5).variance.values
```

**For QA/QC**: predict next-day vol → scale strategy exposure inversely.
Standard practice in CTA / managed-futures.

**Read**: Engle 1982 (Nobel-winning original); Hamilton ch. 21.

---

## 3. Information theory

Standard linear correlation misses nonlinear dependencies. Information
theory generalizes.

### 3.1 Mutual information (MI)

`MI(X, Y) = 0` iff X, Y are independent — captures arbitrary nonlinear
dependence, not just linear correlation. Useful for feature selection
when relationships are non-monotonic (e.g., factor predicts returns in
a U-shape).

```python
from sklearn.feature_selection import mutual_info_regression
mi_scores = mutual_info_regression(X_features, y_returns)
# mi_scores has one value per feature; rank to pick top-k
```

**For QA**: rank candidate factors by MI vs forward returns. Catches
factors that have low Pearson correlation but real predictive structure.
López de Prado uses MI heavily in MLAM.

**Read**: López de Prado, *Machine Learning for Asset Managers* (MLAM)
ch. 3.

### 3.2 Transfer entropy

Directional version of MI: `TE(X → Y)` measures how much knowing X's
past reduces uncertainty about Y's future, beyond Y's own past. Useful
for lead-lag analysis between assets.

```python
from PyIF import te_compute
te = te_compute.te_compute(X, Y, k=1, embedding=1)
```

**For QC**: identify lead-lag pairs (e.g., does crude oil lead energy
stocks?). For QA: probably overkill given cross-sectional setup.

**Read**: Schreiber 2000 paper "Measuring Information Transfer."

---

## 4. Causal inference (the López de Prado push)

Most factor "discoveries" are spurious correlations. Causal inference
asks: would the factor still predict returns under intervention (i.e.,
in a different market regime)? Or is it just hitching a ride on a
confounder?

### 4.1 Pearl's do-calculus / structural causal models

Build a DAG of suspected causal relationships, identify backdoor and
frontdoor paths, compute causal effect (not just correlation) via
do-operator.

```python
import dowhy
model = dowhy.CausalModel(
    data=df,
    treatment="signal",
    outcome="return_5d",
    common_causes=["market_beta", "sector_beta", "size"],
)
estimand = model.identify_effect()
estimate = model.estimate_effect(estimand, method_name="backdoor.linear_regression")
```

### 4.2 Rubin's potential outcomes

Match treated (high-signal) days to control (low-signal) days on
pre-treatment covariates → causal effect = mean difference in outcomes.
Used in econometrics extensively.

**For QA**: quantify how much of a factor's measured return comes from
*causal* exposure to a mechanism vs *correlation* with confounders
(market beta, sector tilt, size).

**Read**: López de Prado, *Causal Factor Investing* (CFA Institute
Research Foundation, 2023). Pearl, *Causality* (2009). Hernan &
Robins, *Causal Inference: What If* (free PDF).

---

## 5. Stochastic calculus / pricing — minimal for non-derivatives shop

Black-Scholes-Merton, Itô calculus, Geometric Brownian Motion. Required
for options, FX forwards, interest-rate derivatives. **Not required**
for cross-sectional equity factor mining. If you ever touch options
overlays:

```python
from py_vollib.black_scholes import black_scholes
price = black_scholes(flag='c', S=100, K=105, t=30/365, r=0.05, sigma=0.20)
```

**For QA today**: defer. For QC if you ever do covered-call overlays
on signals: required.

**Read**: Hull, *Options, Futures, and Other Derivatives* (8th ed.+).
Wilmott, *Paul Wilmott Introduces Quantitative Finance*.

---

## 6. Random matrix theory (RMT) — denoising covariance

When you estimate the covariance matrix of N assets from T returns
with N close to T, the eigenvalues are dramatically distorted by noise.
Marchenko-Pastur theorem gives the *expected eigenvalue distribution
under pure noise* — eigenvalues outside that range carry signal;
eigenvalues inside are noise.

Apply to portfolio construction: shrink the noisy eigenvalues toward
their mean, keep the signal eigenvalues, reconstruct a denoised cov
matrix. **Hierarchical Risk Parity (HRP)** uses this to build
risk-parity portfolios that don't blow up in market stress.

```python
import riskfolio as rp
port = rp.Portfolio(returns=returns_df)
port.assets_stats(method_mu='hist', method_cov='ledoit')  # Ledoit-Wolf shrinkage
weights = port.optimization(model='HRP', rm='MV')
```

**For QA**: don't directly need this for factor mining. For QC's
portfolio-construction layer (combining N strategies into a portfolio),
HRP is the standard.

**Read**: López de Prado, *MLAM* ch. 4 (HRP). Bailey & López de Prado
RMT paper (SSRN 2741146).

---

## 7. Signal extraction — Fourier, wavelets, EMD

Extract structure at specific time scales from noisy returns:
- **FFT**: known periodicities (e.g., monthly rebalancing, FOMC weeks)
- **Wavelets**: localized time-frequency analysis (vs FFT's global)
- **Empirical Mode Decomposition (EMD)**: data-driven decomposition
  into intrinsic mode functions; better than wavelets when basis
  functions can't be assumed

```python
import pywt
coefs = pywt.wavedec(returns, 'db4', level=4)  # discrete wavelet decomp
# coefs[0] = approximation (low-frequency / trend)
# coefs[1..4] = detail (high-frequency / noise)
```

**For QA**: probably overkill — cross-sectional ranking doesn't need
high time-resolution. For QC if doing intraday: wavelet denoising can
clean noisy minute-bar features before strategy logic.

**Read**: Mallat, *A Wavelet Tour of Signal Processing*. Huang et al.
1998 EMD paper.

---

## 8. Distributional robustness

Mean-variance optimization implicitly assumes Gaussian returns. Returns
aren't Gaussian — fat tails matter. Robust alternatives:

### 8.1 CVaR (Conditional Value-at-Risk) optimization

Minimize expected loss in the worst 5% of cases (vs minimizing variance).
Convex, well-supported by `cvxpy` + RiskFolio-Lib.

```python
port.optimization(model='Classic', rm='CVaR', alpha=0.05)
```

### 8.2 Distributionally Robust Optimization (DRO)

Optimize against the worst case over a *family* of distributions
(within e.g. a Wasserstein ball around the empirical distribution).
Hedges against model misspecification.

**For QC's portfolio construction**: use CVaR as the risk measure
instead of variance. **For QA**: not directly applicable.

**Read**: Rockafellar & Uryasev 2000 (CVaR original). Esfahani &
Kuhn 2018 Wasserstein DRO paper.

---

## 9. Triple-barrier labeling (López de Prado)

Standard ML labels for quant: `y = price[t+5]/price[t] - 1` (fixed-
horizon return). Problem: ignores that real strategies exit early on
stops or take profits.

Triple-barrier defines the label as whichever of three barriers hits
first:
- **Upper** (profit target): +2σ
- **Lower** (stop loss): -2σ
- **Time** (max holding): N days

Label = +1 (profit), -1 (stop), or 0 (time-out near zero). Closer to
how a strategy actually exits.

```python
# Pseudocode — see AFML ch. 3 for full implementation
def triple_barrier(close, vol, t1, sigma_pt=2.0, sigma_sl=2.0):
    for t0 in close.index:
        path = close.loc[t0:t1[t0]]
        upper = close[t0] * (1 + sigma_pt * vol[t0])
        lower = close[t0] * (1 - sigma_sl * vol[t0])
        # Find first-touched barrier
        ...
```

**For QA**: alternative label function in `conf_baseline.yaml`. Spec:
[phase_13](phase_13_admission_gate_upgrades.md).

**Read**: AFML ch. 3.

---

## 10. Fractional differentiation

Standard differencing (`returns = price.diff()`) makes a series
stationary but destroys long-memory structure. **Fractional
differencing** (order between 0 and 1) makes the series stationary
while preserving memory.

```python
# Pseudocode — see AFML ch. 5
def fractional_diff(series, d=0.4, threshold=1e-5):
    weights = compute_fracdiff_weights(d, len(series), threshold)
    return convolve(series, weights)
```

**For QA**: feature engineering. Use `fracdiff(price, d=0.4)` as a
predictor instead of `returns`. Preserves trend information that
returns destroy.

**Read**: AFML ch. 5. Hosking 1981 paper on fractional differencing.

---

## 11. Meta-labeling (López de Prado)

Two-stage classifier: first model predicts direction (long/short/skip);
second model predicts whether to **act on** the first model's
prediction. Increases precision by filtering low-confidence trades.

```
First model: signal → {-1, 0, +1}
Second model: (signal, market state, signal confidence) → {act, don't act}
Final position: signal × act
```

**For QA**: train a meta-model on top of the LightGBM predictions —
inputs = (factor predictions, regime label, recent vol). Output = act
or don't. Filters out low-confidence days where the factor is
unreliable.

**Read**: AFML ch. 3.

---

## 12. Statistical learning theory — overfitting bounds

How much *true* generalization should we expect from a model with K
parameters trained on N samples? PAC-learning bounds answer this.

For practical use: use VC dimension / Rademacher complexity to set
*lower bounds* on required N. If you're training a 100-tree XGBoost
with depth 6 (~800 leaves) on 5000 days × 500 stocks (2.5M observations),
you're fine. On 252 days × 50 stocks (12K observations), you're
overfitting.

**For QA**: rough rule — trees + leaves should be << √(N_samples).
Already enforced implicitly by LightGBM's early stopping, but worth
knowing the math.

**Read**: Vapnik, *The Nature of Statistical Learning Theory* (2nd ed.).
Hastie/Tibshirani/Friedman, *Elements of Statistical Learning*, ch. 7.

---

## How LLM-driven mining + math methods complement each other

The LLM's strength: vast prior knowledge, generative diversity, natural-
language hypothesis articulation. Its weakness: easy to fool with
spurious correlations, no native sense of statistical rigor.

The math's strength: rigorous selection-bias correction, structural
inference, generalization bounds. Its weakness: requires hypotheses to
test (no generative side).

**The integration pattern this stack already partially uses:**

```
LLM proposes hypothesis + factor expression       (LLM generative)
   ↓
qlib computes factor + LightGBM scores it          (mechanical)
   ↓
DSR / CPCV / FF residual / ... gate                (math-rigorous, NEW)
   ↓
Memory service stores curated card                 (phase 18)
   ↓
LLM proposes next factor with memory context       (back to LLM, less spurious)
```

The phases 13-19 are the math layer's contribution to this loop.
LLM-driven without math = noise generator. Math without LLM = no ideas
to test. Together: structured search with rigor.

---

## Recommended reading order

If you read nothing else from this list, read in order:

1. **López de Prado, *Advances in Financial Machine Learning* (2018)**
   — chapters 3 (triple-barrier), 4 (sample weights), 7 (CPCV),
   14 (backtest statistics), 17 (structural breaks). 2-3 weekends.
   Required for any quant ML work.
2. **López de Prado, *Machine Learning for Asset Managers* (2020)**
   — chapter 4 (HRP / denoised covariance). 1 weekend.
3. **Stefan Jansen, *Machine Learning for Algorithmic Trading*** + repo
   [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading)
   — best free executable reference.
4. **Hamilton, *Time Series Analysis* (1994)** — chapters on cointegration
   (19), GARCH (21). Standard reference.
5. **López de Prado, *Causal Factor Investing* (CFA Institute, 2023)**
   — when you start asking "is this factor real or just style tilt?"
6. **Bishop, *Pattern Recognition and Machine Learning*** ch. 13 — for
   HMM if you want the rigorous version.

---

## Cross-references

- [research_pipeline.md](research_pipeline.md) — overview index of the
  full research pipeline
- [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md)
  — DSR + CPCV + triple-barrier in production
- [phase_15_hmm_regime_layer.md](phase_15_hmm_regime_layer.md) — HMM
  applied to QA
- [phase_16_signal_stacking.md](phase_16_signal_stacking.md) — the math
  of signal combination (1+(N-1)c formula + HRP)
- [phase_18_factor_memory_service.md](phase_18_factor_memory_service.md)
  — MemGovern-inspired memory layer
