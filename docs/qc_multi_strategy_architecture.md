# QuantConnect Multi-Strategy Architecture

This doc revisits QC integration from a wider angle. The previous QC doc ([phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md)) framed integration as "deploy the QA model on QC" — a single-strategy view. That's only one possible architecture. QC supports many strategies running side by side, and the QA model can play very different roles in each. This doc explains how to think about that.

---

## The framing shift

```
Old framing (limited)                    New framing (correct)
─────────────────────                    ─────────────────────
                                                              
QuantConnect = "where my QA           QuantConnect = a general algo
strategy runs"                        trading platform                
                                                              
Path A: QA model → top-50 buys        QA model is ONE signal source.   
Path B: same, in-broker               Strategies are ABOVE the signal
Path C: same, via API                 layer. You can run any number of
                                      strategies, each consuming
                                      different signal mixes.
```

The single-strategy view confuses two questions that should be separate:
1. **How do I run my QA model in QC?** — answered by Phase 5/6 + the original Paths A/B/C
2. **What strategies do I want to run on QC?** — orthogonal; each strategy decides whether/how to consume the QA model

The right mental model: **Phase 5/6 produce a model bundle that's a *signal source*. Strategies are programs that consume signals and produce orders.** Multiple strategies can share one signal source.

---

## What QC actually is

QC is an algorithmic trading platform. It gives you:

- **Data**: historical + live OHLCV, fundamentals, options chains, alternative data (Twitter/news/etc.), all via a unified Python/C# API
- **Backtester**: replay any strategy on historical data with realistic fills, slippage, costs
- **Live execution**: paper-trading sandbox + real broker connections (IB, Coinbase, etc.)
- **Algorithm framework**: the structure your trading code lives inside
- **Object Store**: cloud storage for files (your model bundle, signals CSVs, lookup tables)
- **Universe selection**: dynamic stock filtering (e.g. "S&P 500 only," "stocks above $5")

Crucially, **QC doesn't care what your strategy is.** A momentum strategy, a mean-reversion strategy, a pairs trading strategy, an ML-based strategy — all are just Python classes that override the same handful of methods. The framework is strategy-agnostic.

---

## Where the QA model fits across different strategy patterns

The QA model produces a **score per stock per day**: "how likely is this to outperform tomorrow?" That's a generic signal. Different strategies use it in different ways.

| Strategy pattern | What it does | Role of QA model |
|---|---|---|
| **Long-only top-K rebalance** | Hold the N highest-scoring stocks; rotate daily | **Direct ranker** — score → ranking → portfolio |
| **Long-short market-neutral** | Long top-K, short bottom-K (cancel beta) | **Direct ranker, both ends** |
| **Mean reversion** | Buy oversold (RSI < 30), sell overbought | **Filter** — only trade reversion on stocks the QA model also likes |
| **Momentum / trend** | Buy stocks at 52-week highs with rising volume | **Confirm** — QA score must agree with momentum signal |
| **Pairs trading** | Trade divergences between correlated stock pairs | **Pair selector** — use QA scores to pick which pairs to trade |
| **Sector rotation** | Rotate among 11 sector ETFs based on relative strength | **Aggregator** — average QA scores per sector → sector strength |
| **Vol-regime-gated** | Trade only when VIX < threshold | **Signal source** while gate is separate (don't trade if VIX > 30, regardless of model) |
| **Earnings-event** | Position before earnings based on expected reaction | **Quality filter** — only trade events on QA-favored stocks |
| **Index arbitrage** | Buy underweighted, sell overweighted index components | **Not used** — pure mechanical strategy, no need for a predictive model |
| **HFT / market making** | Provide liquidity, capture spread | **Not used** — millisecond-scale, QA's daily horizon is wrong |

A single Phase 5 bundle can serve 5 of those strategies simultaneously. The bundle is just data; what each strategy does with it is independent.

---

## QC's Alpha Framework — the right multi-strategy architecture

QC ships with a **modular framework** that splits an algorithm into pluggable components. This is what you should build toward if you're running more than one strategy.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         QC Algorithm                                  │
│                                                                       │
│  ┌────────────────────┐                                               │
│  │ Universe Selection │  → which stocks are eligible today?          │
│  │ Model              │    (S&P 500, $5+ price, etc.)                │
│  └─────────┬──────────┘                                               │
│            │                                                          │
│            ▼                                                          │
│  ┌────────────────────┐  ┌────────────────────┐  ┌─────────────────┐ │
│  │  Alpha Model 1     │  │  Alpha Model 2     │  │  Alpha Model N  │ │
│  │  (QA-based)        │  │  (mean-reversion)  │  │  (...)          │ │
│  │  produces "Insight"│  │  produces Insight  │  │  produces Insight│ │
│  └─────────┬──────────┘  └─────────┬──────────┘  └────────┬────────┘ │
│            │                       │                      │          │
│            └───────────────────────┼──────────────────────┘          │
│                                    ▼                                  │
│                       ┌────────────────────────┐                      │
│                       │ Portfolio Construction │  → combine insights │
│                       │ Model                  │    into target weights│
│                       └────────────┬───────────┘                      │
│                                    ▼                                  │
│                       ┌────────────────────────┐                      │
│                       │ Risk Management Model  │  → cap exposure,    │
│                       │                        │    stop-loss, etc.   │
│                       └────────────┬───────────┘                      │
│                                    ▼                                  │
│                       ┌────────────────────────┐                      │
│                       │ Execution Model        │  → place orders     │
│                       │                        │    (VWAP/TWAP/market)│
│                       └────────────────────────┘                      │
└──────────────────────────────────────────────────────────────────────┘
```

Each box is a separate Python class. You implement them once, then **mix and match**.

### What each component does

- **Universe Selection Model** — what stocks are available to trade on a given day. *(e.g. "top 500 by market cap that have > $5M daily dollar volume")*
- **Alpha Model** — produces *Insight* objects: "I think AAPL will go up over the next 5 days." This is where each strategy's logic lives. **Multiple Alpha Models can run simultaneously, each producing their own insights.**
- **Portfolio Construction Model** — takes all the insights from all alpha models and decides target portfolio weights. Can equal-weight, risk-weight, optimize, ensemble, etc.
- **Risk Management Model** — applies overlays: max position size, stop-losses, drawdown limits, sector caps. Can veto trades.
- **Execution Model** — turns target weights into actual orders. Market-on-open, VWAP throughout the day, etc.

### Where the QA model lives

```python
class QAAlphaModel(AlphaModel):
    """One alpha model among potentially many. Consumes the Phase 5 bundle."""
    
    def __init__(self, bundle_path):
        self.model = joblib.load(bundle_path / "model.lgbm")
        self.factors = yaml.load(bundle_path / "factor_expressions.yaml")
    
    def Update(self, algorithm, data):
        # Compute features for each stock in the universe
        features = self.compute_features(data)
        # Run model
        scores = self.model.predict(features)
        # Emit Insights (long top-50, short bottom-50, etc.)
        return [Insight(symbol, ...) for symbol, score in scores.items()]
```

Then in your `Initialize()`:

```python
self.AddAlpha(QAAlphaModel(bundle_path))           # QA-driven signals
self.AddAlpha(MeanReversionAlphaModel())           # mean-reversion signals
self.AddAlpha(MomentumAlphaModel())                # classical momentum
self.SetPortfolioConstruction(EqualWeightingPortfolioConstructionModel())
```

The Portfolio Construction Model receives insights from **all three alpha models**, decides what to do with them. You can weight them, take majority votes, run them in different sleeves, etc.

This is the QC-native way to run multiple strategies that may share signals.

---

## Three architecture options, easiest to most flexible

### Option 1 — One algorithm per strategy

Each QC algorithm is single-purpose. If you want to run 3 strategies, you have 3 separate QC projects with 3 separate accounts (or sub-accounts).

```
QC project A: "QA top-50 long-only"   → IB account 1
QC project B: "Mean reversion"         → IB account 2
QC project C: "Sector rotation"        → IB account 3
```

- **Pros**: Trivially simple. Each strategy is isolated; debugging one doesn't risk the others.
- **Cons**: Can't combine signals across strategies. Each project re-implements universe selection, execution, etc. If you want strategy A's filter to gate strategy B, you can't.
- **When to use**: First proof of concept. Get one strategy working in QC end-to-end before architecting for many.

### Option 2 — One algorithm, multiple Alpha Models (QC's framework)

Use the framework architecture diagram above. One QC project, multiple Alpha Models inside it, one shared Portfolio Construction Model.

```
QC project "Multi-strategy long-short":
  Universe: S&P 500
  Alphas:
    - QAAlphaModel (the Phase 5 bundle)
    - MeanReversionAlphaModel
    - MomentumAlphaModel
  Portfolio Construction: insight-weighted
  Risk: max 5% per position, max 30% sector, 10% stop-loss
  Execution: market-on-open
```

- **Pros**: All strategies share one universe + one risk overlay + one execution. Insights can be combined intelligently. Sharpe usually improves vs. running them separately because of diversification.
- **Cons**: More code. One bug can affect all strategies. Need to think about how Portfolio Construction combines conflicting insights ("alpha A says BUY, alpha B says SELL").
- **When to use**: Once Option 1 has proven a single strategy works, this is where you go.

### Option 3 — Strategy of strategies (regime-aware)

A meta-algorithm chooses which strategy to run based on market regime.

```
QC project "Regime-aware":
  if VIX < 20:    activate trend/momentum + QA
  if VIX 20-30:   activate mean-reversion only
  if VIX > 30:    cash, except defensive sectors
```

- **Pros**: Adapts to market conditions. Can be very robust through regime changes.
- **Cons**: Hard to design well — picking regimes is itself a hard problem. Easy to overfit "regime gates" on backtest history.
- **When to use**: Advanced. Skip until Options 1 and 2 are working.

---

## Concrete strategy examples (how each uses QA)

These are sketches of what each Alpha Model would do, not full implementations.

### A. Long-only top-K rebalance — original Path A

```
Each morning at 9:30 ET:
  scores = QA_model.predict(today_features)
  target = top 50 by score
  rebalance to equal-weight target
```

QA role: **direct ranker.**

### B. Long-short market-neutral

```
Each morning:
  scores = QA_model.predict(today_features)
  long_book = top 50 (long, +1% each)
  short_book = bottom 50 (short, -1% each)
  Net dollar exposure = 0 (market-neutral)
```

QA role: **direct ranker, both directions.** This is what most quant funds run because it removes market risk.

### C. Mean reversion gated by QA

```
Each morning:
  RSI_oversold = stocks with RSI(14) < 30
  scores = QA_model.predict(today_features)
  
  # Only buy oversold stocks the model also likes
  candidates = RSI_oversold ∩ {top 100 by QA score}
  
  Position size: equal-weight, max 20 holdings
  Exit when RSI > 50 or after 5 trading days
```

QA role: **quality filter** to avoid mean-reverting "value traps." Pure RSI mean reversion catches falling knives; QA's predictive layer should reduce the false positives.

### D. Momentum with QA confirmation

```
Each morning:
  momentum_score = (52-week return) for each stock
  qa_score = QA_model.predict(today_features)
  
  # Composite: stocks must be in top 30% on BOTH metrics
  candidates = top_30pct(momentum) ∩ top_30pct(qa_score)
  
  Hold equal-weight, weekly rebalance
```

QA role: **co-signer.** Reduces false-positive momentum on stocks the model thinks are stretched.

### E. Sector rotation

```
Each Monday:
  for each of 11 GICS sectors:
    sector_qa_score = mean(qa_score for stocks in this sector)
  
  rank sectors by sector_qa_score
  rotate into top-3 sectors via XLK / XLF / etc. ETFs
  weight by score (or equal-weight)
```

QA role: **aggregator.** Per-stock scores collapse into per-sector strength, used to rotate sector ETFs. Much lower turnover than per-stock strategies.

### F. VIX-regime-gated

```
Each morning:
  if VIX(today) < 20:
    activate strategy A (top-K long)
    target: 100% invested
  elif 20 <= VIX(today) < 30:
    keep current positions, no new entries
  else (VIX >= 30):
    de-risk: 50% cash, 50% defensive stocks (utilities, staples)
```

QA role: **provides signals** while VIX gate decides whether to act on them.

### G. Pairs trading with QA-filtered pair selection

```
Build candidate pairs:
  for each pair (A, B) where A and B are in same sector:
    cointegration_p = test_cointegration(A.prices, B.prices)
    qa_quality = (qa_score(A) + qa_score(B)) / 2
    if cointegration_p < 0.05 AND qa_quality > median:
      add (A, B) to active pairs
  
Each day for each active pair:
  spread = z_score(A.price - β·B.price, lookback=60)
  if spread > 2:  short A, long B
  if spread < -2: long A, short B
  exit when spread crosses 0
```

QA role: **pair quality filter** — only trade pairs where both stocks are model-favored, avoiding pairs with deteriorating fundamentals.

---

## What stays the same vs. what's strategy-specific

### What's the same across all strategies (Phase 5/6 outputs)

- **Phase 5 model bundle** — produced once, reused by every strategy that wants the QA score
- **`predict_with_production_model.py`** — the offline path for daily CSV generation works for any strategy that wants a "QA score for stock X on day Y"
- **`compute_factors_fresh.py`** (future work) — for in-broker inference, this script computes factor values from raw OHLCV; reusable across strategies
- **The factor expressions** in `factor_expressions.yaml` — same for everyone

### What's strategy-specific (lives in QC)

- The **Alpha Model class** for each strategy
- The **Universe Selection** rules (some strategies want SP500, some want sector ETFs, some want only liquid stocks)
- The **Portfolio Construction** logic (long-only equal-weight vs. long-short risk-parity vs. Black-Litterman)
- The **Risk Management** overlays (varies by strategy's risk profile)
- The **Execution Model** (some strategies want market-on-open, some want VWAP, some want limit orders)

The clear split: **back-end (Phase 5/6) is shared infrastructure. Front-end (QC strategy code) is per-strategy.**

---

## Where my original Path A/B/C fit in this picture

The original three paths were really three different ways to do the **back-end-to-front-end handoff**, not three different strategies:

| Original path | What it actually was | Where it sits in this new picture |
|---|---|---|
| Path A: Daily CSV upload | How model predictions get to QC | Works for any strategy. The CSV is consumed by whatever Alpha Model the strategy uses. |
| Path B: In-broker inference | Same handoff, but inside QC | Works for any strategy. Faster, less external dependency. |
| Path C: REST API | Same handoff, but via HTTP | Works for any strategy. Most flexible but most operational complexity. |

So the right reading: **Path A/B/C are about *how to get the QA score into a QC algorithm***. The strategy itself (top-K, mean-reversion, sector rotation, etc.) is a different layer.

You can mix: e.g., a strategy that uses QA as one input + a fundamentals-based filter + a momentum signal. The QA part comes via Path A, the others via QC-native data APIs, all combined in one Alpha Model.

---

## Recommended evolution path (concrete sequencing)

This builds on the previous doc's recommendation but extends it for multi-strategy.

### Stage 1 — One strategy, one path *(week 1)*

Get **Path A + Strategy A (top-K long-only)** working end-to-end. Just one strategy. Just one path.

- Phase 5 bundle ready ✓
- Phase 6 produces daily CSVs ✓
- One QC algorithm reads the CSV and trades top-50
- Backtest in QC for 2017-2020 (matches our test window) and confirm decent Sharpe

**Goal:** prove the QA model produces tradeable signals when subjected to QC's realistic execution.

### Stage 2 — Refactor into Alpha Framework *(week 2-3)*

Take the Stage 1 algorithm and split it into the framework components:

- `QAAlphaModel` (consumes the CSV, emits Insights)
- Default Universe / Portfolio Construction / Execution

No new strategies yet. Just the framework refactor.

**Goal:** make adding a second strategy a 1-day task instead of a multi-day refactor.

### Stage 3 — Add a non-QA strategy *(week 4)*

Add `MeanReversionAlphaModel` (RSI-based) running side by side with `QAAlphaModel`. Same universe, same execution, two alpha sources combined by Portfolio Construction.

**Goal:** prove the multi-Alpha architecture works. Diversification benefit should show up — combined Sharpe > each individually.

### Stage 4 — Add filtered/composite strategies *(week 5+)*

Add the more complex patterns from the table: QA-filtered mean reversion, QA-confirmed momentum, sector rotation. Each becomes another Alpha Model in the same algorithm.

### Stage 5 — Live paper trade, then capital *(week 6+)*

Run paper-trading in QC for 4-6 weeks. Compare to backtest. If consistent, switch to small capital.

### Stage 6 (long-term) — Move to Path B or C

Once you trust the system, decide whether the daily-CSV handoff is good enough or whether you want in-broker inference (Path B) for fully autonomous operation.

---

## What this means for what's already built

Every script we've built so far stays relevant. None of it is wasted on the multi-strategy view:

| Built | Used for | Strategy-coupled? |
|---|---|---|
| `extract_production_model.py` (Phase 5) | Producing the model bundle | No — same bundle for all strategies |
| `predict_with_production_model.py` (Phase 6) | Generating prediction CSVs | No — same CSV consumable by any strategy |
| `run_baseline_anchor.py` | Anchor for measuring uplift | No — useful for any model evaluation |
| `admission.py` | Pool diversity filter | No — internal to mining |
| Mining loop changes (mutation/crossover) | Better factor mining | No — produces better bundles, not better strategies |

What's **not yet built** but needed for multi-strategy:

| Not built | Stage needed at | Note |
|---|---|---|
| `predict_for_quantconnect.py` | Stage 1 | Outputs CSV in QC's expected format |
| QC Algorithm template | Stage 1 | The actual C# or Python class for QC |
| `QAAlphaModel` (Alpha Framework class) | Stage 2 | The reusable component for Stage 2+ |
| `compute_factors_fresh.py` | Stage 6 | Required for Path B (in-broker inference) |
| Other Alpha Models (mean reversion, momentum, etc.) | Stage 3+ | Implementations of the pattern table |

---

## Summary

The previous QC doc was right about *how* to deploy the QA model. This doc adds the missing layer: *what strategies* can use it, and how to organize them.

**Three takeaways:**

1. **Phase 5/6 are foundational regardless of strategy count.** They produce the signal source. Build them right and they serve every strategy you ever write.

2. **QC's Alpha Framework is the multi-strategy architecture.** When you have 2+ strategies, refactor into it. Don't try to bundle multiple strategies into one monolithic algorithm.

3. **Start with one strategy.** Don't build the multi-strategy framework before you have one strategy that works in production. Stage 1 → Stage 2 → Stage 3 in order. Each stage adds one new dimension; trying to skip stages produces architecture that doesn't actually fit any real workload.

When you're ready to start Stage 1, I can write `predict_for_quantconnect.py` (a thin wrapper around Phase 6 that outputs in QC's expected CSV format) and a Python QC algorithm template that consumes it. That's the smallest piece that gets you to a working QC backtest using your QA model.
