# Full Research Pipeline — Real Quant Workflow as Code

Status: 📋 plan (no code yet) — 2026-05-09

QuantaAlpha + QuantaQC implement two pieces of a real quant team's
process: factor mining (QA) and strategy mining (QC). This doc maps the
remaining stages — idea sourcing, hypothesis formalization, data
readiness, risk decomposition, live monitoring, knowledge persistence —
into a concrete buildable plan.

The aim: turn "we have factor mining + strategy mining" into "we have a
quant research firm in code."

---

## The full quant research lifecycle (10 stages)

What a working quant team actually does, in order. Each stage feeds
the next; the loop closes at stage 10 → stage 0.

| # | Stage | What happens in a real team | Where we are today |
|---|---|---|---|
| 0 | **Idea sourcing** | Read arXiv q-fin / SSRN / sell-side notes / news; surface candidate hypotheses to test | ❌ no tool — user types objectives by hand into the QA chat input |
| 1 | **Hypothesis formalization** | "Intuition" → spec: feature + universe + horizon + expected sign + magnitude | ⚠️ partial — QA's planner does this implicitly inside the mining loop, but no upstream filter / queue |
| 2 | **Data readiness check** | Do we have the features this hypothesis needs? Survivorship bias? Point-in-time? | ❌ no pre-flight — bad hypotheses waste mining LLM tokens |
| 3 | **Factor mining** | Build the signal, score it cross-sectionally, evolve via mutation/crossover | ✅ QA |
| 4 | **Walk-forward validation** | Test factor stability across regimes / time windows | 📋 sketched ([walk_forward_validation.md](walk_forward_validation.md)) — not built |
| 5 | **Risk decomposition** | What's the alpha *after* factor exposure (FF3/5, Barra)? Sector tilts? Correlation with existing book? | ❌ not built — we don't know if mined factors are just style tilts |
| 6 | **Strategy construction** | Wrap signal in entry/exit/sizing rules, position management | ✅ QC |
| 7 | **Parameter optimization** | Walk-forward optimization, hyperparameter robustness | ✅ QC Phase 6 (shipped) |
| 8 | **Live / paper deployment** | Real-money OOS test on QC paper-trading | 📋 sketched (QC Phase 11/12) |
| 9 | **Monitoring + decay detection** | Watch for performance erosion vs IS; trigger refresh when alpha decays | ❌ not built |
| 10 | **Knowledge persistence** | "What worked, what didn't, why" — feed back into stage 0 next cycle | ⚠️ partial — auto-publish to QuantaAlphaFindings captures factors but not lessons |

**Solid: 3, 6, 7. Sketched: 4, 8. Missing: 0, 1, 2, 5, 9, 10.**

That gap is what makes "real quant" different from "factor miner + strategy miner."

---

## The user's proposed flow vs the full picture

User originally proposed:
**research pipeline → QA → build model → QC**

That maps to stages 0/1 → 3 → (Phase 5/6 model bundle) → 6/7. Missing:
- Stage 2 (data readiness)
- Stage 4 (walk-forward validation)
- Stage 5 (risk decomposition — biggest honest-alpha blind spot)
- Stage 8 (live deployment)
- Stage 9 (decay monitoring)
- Stage 10 (the feedback loop that closes the cycle)

The middle 3 → 7 is the shiny part most papers focus on. The flanking stages (0, 1, 2 upstream; 5, 9, 10 downstream) are where most real-quant work actually happens.

---

## Architecture — proposed end state

```
┌─────────────────────────────────────────────────────────────────┐
│ QuantaResearch (NEW project, sibling of QA/QC)                  │
│                                                                 │
│  Stage 0: Idea sourcing                                         │
│   ├─ arxiv_crawler.py    (daily q-fin paper fetch)             │
│   ├─ semantic_scholar.py (citation graph + abstracts)          │
│   ├─ nber_rss.py         (NBER working papers feed)            │
│   ├─ alpha_architect.py  (weekly anomaly summaries — RSS)      │
│   └─ → ideas/raw/<date>.json (queue of candidate ideas)        │
│                                                                 │
│  Stage 1: Hypothesis formalization                              │
│   ├─ LLM extracts: feature, universe, horizon, expected effect │
│   ├─ De-dups against existing QuantaAlphaFindings              │
│   ├─ Optional human review queue                                │
│   └─ → ideas/formalized/<id>.json (structured hypotheses)      │
│                                                                 │
│  Stage 2: Data readiness                                        │
│   ├─ Verify required features exist (close, volume, vwap, ...)  │
│   ├─ Verify universe covers required tickers                    │
│   ├─ Survivorship-bias check (point-in-time membership)         │
│   └─ → ideas/ready/<id>.json (data-ready hypotheses)           │
│                                                                 │
│  Stage 2.5: Auto-feed into QA                                   │
│   └─ POST /api/v1/mining/start (with displayName = idea_id)    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                          QuantaAlpha (built — stages 3, partial 4)
                               │
                               ▼
                          QuantaAlphaFindings (built — partial 10)
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
           Stage 4: WF    Stage 5: Risk    Stage 6: Strategy
           validation     decomp (NEW)     (QC, built)
           (sketched)     │
                  │       │            │
                  └───────┴────────────┘
                               │
                               ▼
                       Stages 7→9 (QC + monitoring)
                       Stage 7: ✅ optimization
                       Stage 8: 📋 paper trading
                       Stage 9: ❌ decay monitor (NEW)
                               │
                               ▼
                       Stage 10: feedback to stage 0
                       (NEW: enrich QuantaAlphaFindings with
                        "lessons" — what worked / didn't / why)
```

---

## Tools available for stage 0 (idea sourcing)

Free / ethical sources only (no SSRN scraping — TOS issues):

| Source | Access | What it gives | Refresh rate |
|---|---|---|---|
| **arXiv q-fin** | Free API ([export.arxiv.org/api](http://export.arxiv.org/api)) | Daily new papers tagged q-fin.PM, q-fin.ST, q-fin.TR | Daily |
| **Semantic Scholar API** | Free | Citation graph, abstracts, related-work links | Real-time |
| **NBER working papers** | Free RSS | Top finance/economics WPs | Weekly |
| **Federal Reserve papers** | Free | FEDS papers | Weekly |
| **AlphaArchitect blog** | Free RSS | Curated weekly factor summaries | Weekly |
| **Quantocracy** | Free aggregator ([quantocracy.com](https://quantocracy.com)) | Best-in-class daily curated mashup of practitioner blogs | Daily |
| **AQR research library** | Free ([aqr.com/Insights](https://www.aqr.com/Insights)) | Best public research from any quant fund | Weekly |
| **Twitter/X quant accounts** | API limited | Noisy but timely | Real-time |
| **Quantpedia** | Paid (~$300–500/yr) | ~7K+ curated strategy entries with PDFs + replication code | Weekly |

Free baseline coverage: arXiv + Semantic Scholar + NBER + AlphaArchitect + Quantocracy = ~80% of academic factor flow. Buildable in 1–2 days.

---

## Renaissance principles worth borrowing

What's publicly knowable from Zuckerman's *The Man Who Solved the Market*
(2019) and the Acquired podcast's 4-hour Renaissance episode (March 2024).
The *machinery* (microsecond execution, $100B+ data infra, 300+ PhDs) isn't
replicable by a small team — but the *philosophy* mostly is, and our stack
already embodies parts of it:

| Renaissance principle | Their version | Our analogue / what to add |
|---|---|---|
| **Signal stacking over silver bullets** | 1000s of weak, low-correlation signals; portfolio aggregates | QA's `balanced_composite` + factor pool capped at 50% admission ratio matches. Add: **deduplication by AST + IC-correlation** to enforce low correlation between admitted factors (AlphaAgent regularizer). |
| **HMM-based regime detection** | Robert Mercer + Peter Brown brought Baum-Welch/HMM from IBM speech; hidden states ≈ market regimes | Not in our stack today. Add: small `hmmlearn`-based regime detector (2-3 states on SPY returns + VIX) as a strategy-level on/off gate. ~50 lines. |
| **Models reinvent every ~2 years** | Continuous re-mining is the strategy, not "find the holy formula" | Our Mining → Refine → Optimize → Promote loop matches. Phase 9 (decay monitoring) closes this loop. |
| **Stat-arb / pairs / cointegration as bread and butter** | Multi-asset basket trades on cointegrated spreads | Not in our stack. Add via `statsmodels.tsa.vector_ar.vecm.coint_johansen` + Kalman filter for time-varying hedge ratios. |
| **Short-horizon, high-leverage intraday** | Medallion is mostly intraday futures/equities | NOT replicable for outsiders without low-latency infra + commission relief. Don't try to copy. |

**Net**: Renaissance = signal-stacking + regime-aware allocation + continuous redevelopment. Three of those four are doable in our stack with focused work; intraday HFT isn't and shouldn't be a goal.

---

## Concrete build proposal

A new project `QuantaResearch` (sibling repo, mirroring QA/QC layout):

```
repos/QuantaResearch/
├── .gitignore
├── README.md
├── pyproject.toml
├── docs/
│   ├── roadmap.md
│   └── stage_<n>_<name>.md (per-stage specs as built)
├── quantaresearch/
│   ├── __init__.py
│   ├── sources/
│   │   ├── arxiv.py
│   │   ├── semantic_scholar.py
│   │   ├── nber_rss.py
│   │   └── alpha_architect.py
│   ├── pipeline/
│   │   ├── formalize.py        # LLM: free-text abstract → structured hypothesis
│   │   ├── readiness.py        # data-readiness check vs QA qlib bundle
│   │   └── feed_to_qa.py       # POST to QA's mining/start
│   └── store/
│       ├── ideas_raw/<date>/   # daily snapshot from each source
│       ├── ideas_formalized/   # post-LLM, structured
│       └── ideas_ready/        # post-readiness check
├── scripts/
│   ├── daily_fetch.py          # cron-friendly: run all sources
│   └── feed_top_n_to_qa.py     # take top-N ready ideas, kick off mining
├── frontend-v2/                # optional FE — Vite/React/Tailwind matching QA/QC pattern
│   └── (similar structure to QA's)
└── tests/
```

### Effort + value matrix

| Component | Effort | Value | Build order |
|---|---|---|---|
| Stage 0/1: arXiv + LLM formalizer + auto-feed to QA | **1–2 days** | High — replaces "user thinks of objective" with "system proposes from current academic flow" | **First.** Biggest leverage. |
| Stage 2: Data readiness pre-flight | **4 hours** | Medium — saves wasted mining runs (~$5–20 LLM tokens each) | **Second.** Cheap, immediate cost saver. |
| Stage 5: Risk decomposition (Fama-French) | **1–2 days** | High for honest alpha estimation | **Third.** Reveals if mined factors are pure style tilts (sector, size, value). |
| Stage 9: Live decay monitor | 2–3 days | Only valuable AFTER live deployment exists | **Defer** — gated by QC Phase 11/12 |
| Stage 10: Knowledge persistence + feedback loop | 1–2 days | High long-term, low immediate | **Defer** — needs critical mass of runs first |

---

## Recommended build sequence — NEXT-UP work has dedicated phase docs

Each item below has a full spec doc. This index just orders them.

| Order | Phase | What | Effort | Spec |
|---|---|---|---|---|
| **1** | **13** | Admission gate upgrades (DSR + CPCV + AST-novelty dedup + triple-barrier) | ~1 day | [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md) |
| **2** | **17** | Training-window presets (paper-aligned / recent-regime / stress / walk-forward) in FE Advanced + bundle A/B compare harness | ~half day | [phase_17_continuous_redevelopment.md](phase_17_continuous_redevelopment.md) |
| **3** | **15** | HMM regime detection layer + per-regime strategy mapping table | ~half day | [phase_15_hmm_regime_layer.md](phase_15_hmm_regime_layer.md) |
| **4** | **14** | QuantaResearch sibling project: arXiv crawler + LLM formalizer + data-readiness + auto-feed | ~1-2 days | [phase_14_quantaresearch.md](phase_14_quantaresearch.md) |
| **5** | **16** | Signal stacking: 5 combiners benchmarked, contribution attribution, regime-conditional fits | ~2-3 days | [phase_16_signal_stacking.md](phase_16_signal_stacking.md) |
| 6 | — | FinBERT sentiment on EDGAR 8-Ks (free, real NLP feature stream) | ~1 day | _no spec yet_ |
| 7 | — | Risk decomposition: regress bundle predictions against Fama-French (residual alpha) | ~1 day | _no spec yet_ |
| 8 | 9, 10 | Decay monitor + knowledge persistence | defer | _gated by live deployment_ |

**Build order rationale**: 13 first (honesty fix; all subsequent metrics
depend on it). 17 second (cheap, lets us A/B training windows without
code changes per run). 15 + 14 are independent — pick whichever you
care about more. 16 builds on 13 + 15. 6 + 7 are loose; pick when
relevant.

---

## Human oversight design (decide before building)

The temptation with auto-research is to build a giant pipeline and let
it run unattended. **That's how you produce many bad factors fast.**
Real quant teams have a *lot* of human review at stages 1, 5, 10. Three
oversight modes worth picking between:

| Mode | Pattern | Trade-off |
|---|---|---|
| **Human-in-loop at every transition** | Each stage emits a queue. User approves before next stage runs. | Slow but safest. Recommended early. |
| **Auto-flow with halts on red flags** | Runs end-to-end automatically but pauses if: (a) data-readiness fails, (b) factor doesn't pass walk-forward, (c) risk decomp shows pure beta. User reviews halted runs only. | Good middle ground once we trust each stage. |
| **Full auto with daily summary** | Pipeline runs end-to-end, daily summary email/dashboard of what was attempted + what passed gates. | Lowest oversight; risk of bad factors slipping through to live trading. Avoid until very mature. |

**Recommended**: start with mode 1 (human-in-loop), graduate to mode 2
once stages 0–5 each demonstrate they make sensible decisions on
several dozen ideas, never go to mode 3.

---

## Honest scope notes

- **This is a large project.** A real-quant-process replica is months
  of work, not weeks. The plan above breaks it into ~5 person-days of
  high-leverage work (stages 0, 1, 2, 5) + open-ended ongoing work for
  stages 9, 10. Don't try to build it all in one go.
- **Quality > quantity for ideas.** A daily flow of 100 mediocre
  hypotheses is worse than a weekly flow of 5 well-formalized ones.
  The LLM filter at stage 1 is what determines this — invest in the
  prompt.
- **Risk decomp is more valuable than walk-forward in practice.** If a
  factor is just MOM exposure, walk-forward will say "yes it works"
  because MOM works. Risk decomp says "no, this is just MOM rebadged."
  Build stage 5 before getting fancy with stage 4.
- **Don't auto-deploy to live.** Even with a good pipeline, the gap
  between "passes our 5 gates" and "real money OOS" is large. Keep
  stages 8/9 manual until you've verified ≥3 strategies survive 6+
  months of paper trading.

---

## Reference reading & open-source ecosystem

Curated 2024–2026 survey. Each entry: what it is, why we'd care, alternative.

### LLM-in-quant frameworks worth knowing

| Project | What | Why care | Verdict |
|---|---|---|---|
| **RD-Agent** ([microsoft/RD-Agent](https://github.com/microsoft/RD-Agent), arXiv 2505.15155) | Microsoft's production-grade R&D agent; 5-unit decomposition (Specification/Synthesis/Implementation/Validation/Analysis) joint factor + model optimization. Ships bolted onto qlib. | Closest architectural reference for our pipeline. Steal patterns; don't switch off our stack. | **Required reading** |
| **AlphaAgent** ([RndmVariableQ/AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent), arXiv 2502.16789) | Three regularizers vs alpha decay: AST-novelty, hypothesis-factor alignment, AST-complexity caps. ~81% hit-ratio improvement on CN/US. | Plug-in-able into our Refine phase. The AST-novelty regularizer is what we'd add. | **Required reading** |
| **TradingAgents** ([TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), arXiv 2412.20138) | 7 specialized agents (Fundamentals/Sentiment/News/Technical/Researcher/Trader/Risk Manager) on LangGraph. Multi-LLM (OpenAI/Anthropic/Google/xAI/DeepSeek/Qwen/Ollama). | Closest open analogue to a real-firm workflow. Worth a weekend run. | Worth running |
| **FactorMAD** (ACM AI in Finance 2025) | Multi-agent debate — two LLMs critique factor proposals before code-gen. | Pattern (adversarial review pre-gate) is the value, not the repo. | Pattern only |
| **AlphaSAGE** (arXiv 2509.25055) | GFlowNets for structure-aware factor exploration; addresses cold-start sparse-reward + portfolio diversity. | Niche but novel. Revisit if our pool keeps converging on similar formulas. | Watch |
| **FinGPT** ([AI4Finance/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)) | LoRA-finetuned LLMs for financial sentiment, news + tweets. | Real, usable, not for factor formulas — for **sentiment feature pipelines**. | Use for NLP |
| **FinBERT** ([finbert.org](https://finbert.org)) | Pretrained on 60K 10-Ks + 142K 10-Qs + analyst reports + earnings (1994–2019). 88.2% sentiment accuracy. | Drop-in for ticker-day sentiment as cross-sectional factor. | **Adopt for stage 5b** |
| **FinMem** ([pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading), arXiv 2311.13743) | LLM trading agent with 3-layer memory (short/intermediate/long-term) + character profile. | Memory architecture is the keeper. Relevant for any LLM agent retaining regime context across iterations. | Pattern only |
| **FinRL** ([AI4Finance/FinRL](https://github.com/AI4Finance-Foundation/FinRL)) | RL agents (A2C/DDPG/PPO/TD3/SAC) on Stable-Baselines3 for trading. NeurIPS 2020 origin. | Use RL for **portfolio allocation / execution**, NOT signal generation (fragile rewards, brutal sample efficiency, live perf often disappoints). | Niche use |
| **FinRobot** ([AI4Finance/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)) | AI-agent platform with Financial Chain-of-Thought. | Mostly demo-grade — slicker diagrams than production behavior. | Skip |
| **Alpha-R1** (arXiv 2512.23515) | RL on top of LLM reasoning for alpha screening. | Trend to watch (post-DeepSeek-R1 reasoning-RL wave). | Watch |

### Classical ML — what 2025 actually uses

- **LightGBM** dominates tabular factor prediction (already our default). XGBoost is the safer alternative; CatBoost wins with many cross-sectional categoricals.
- **Sequence models 2025**: Temporal Fusion Transformer (TFT — multi-horizon, interpretable attention, mature in `pytorch-forecasting`), N-BEATS / N-HiTS (pure-MLP residual stacks; surprisingly strong univariate), and **Mamba / state-space models** — the 2025 story. SST hybrid Mamba-Transformer (arXiv 2404.14757), Graph-Mamba, CMDMamba (Frontiers AI 2025) all benchmarked on CSI 300/800 with reported IC/RankIC improvements. Linear-time vs Transformer's quadratic. Worth experimenting once we have a Transformer baseline working.

### Math foundations — what's worth learning

| Topic | Library | Why care | Source |
|---|---|---|---|
| **Hidden Markov Models** for regime detection | `hmmlearn` | Renaissance-grade tool; 50 lines for a working 2-3 state regime gate | Standard |
| **Kalman filter** for online estimation | `filterpy` (preferred), `pykalman` | Dynamic hedge ratios, online OLS, smoothing noisy factors | Standard |
| **Cointegration / Johansen test** for stat-arb | `statsmodels.tsa.vector_ar.vecm.coint_johansen` | Pairs / basket trading; multi-asset spreads | Engle-Granger + Johansen 1991 |
| **Information theory / mutual information** | `sklearn.feature_selection.mutual_info_regression` | Nonlinear feature selection; better than linear corr when relationships are non-monotonic | López de Prado, *MLAM* |
| **Deflated Sharpe Ratio** | DIY (~30 lines NumPy) | Corrects for selection bias when reporting best-of-N. **Required for any factor mining stack.** | Bailey & López de Prado, SSRN 2460551 |
| **Combinatorial Purged CV** | DIY or `mlfinlab` | Walk-forward CV leaks across overlapping label horizons; CPCV is the fix | López de Prado, *AFML* ch. 7 |
| **Causal inference for factors** | `dowhy`, `causalml` | Most factor "discoveries" are spurious correlations; causal graphs reveal which | López de Prado, *Causal Factor Investing* (CFA Institute 2023) |

### Backtest / portfolio frameworks

| Tool | Best for | Verdict |
|---|---|---|
| **qlib** (Microsoft) | Cross-sectional ML factor research, Alpha158/360, integrated DL | Already on it. Keep. |
| **QuantConnect Lean** | Production-grade event-driven backtesting + live trading | Already on it. Keep. |
| **vectorbt-pro** (paid) / vectorbt | Vectorized backtesting at scale, parameter-grid sweeps in Numba | Fastest for *research* parameter scans. Pro version is paid. |
| **NautilusTrader** | High-perf event-driven, Rust core | Serious alternative to Lean. Don't migrate without reason. |
| **RiskFolio-Lib** ([dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)) | Convex portfolio optimization (24 risk measures, HRP, NCO, CVaR, etc.) on CVXPY | **Adopt** when we add a serious optimizer. Active dev (v7.2.1, Feb 2026). |
| **skfolio** ([skfolio.org](https://skfolio.org)) | Newer, scikit-learn-style portfolio optimization | Modern alternative if we prefer sklearn idioms. |
| **PyPortfolioOpt** | Simpler MV/HRP/Black-Litterman | Lighter-weight RiskFolio alternative. |
| **alphalens-reloaded** | Factor IC analysis, quantile returns | Define the vocabulary (IC, IR, quantile spread). Use for analysis dashboards. |
| **quantstats** | Modern tear-sheet style perf/risk reports | Use over deprecated pyfolio. |

### Alt-data sources — free vs paid

- **SEC EDGAR** (free) — 10-K/10-Q/8-K filings. Use [`edgartools`](https://github.com/dgunning/edgartools) Python package. **Highest-ROI alt-data for an outsider.**
- **GDELT** (free) — global news events DB. Useful but noisy.
- **Reddit (PRAW)** (free) — r/wallstreetbets sentiment was a real factor 2021–24. Supplementary, not primary.
- **Twitter/X** — post-2023 paywall, $5K/mo for serious volume. Skip unless funded.
- **Earnings call transcripts** — paid (Refinitiv / Capital IQ / FactSet / SeekingAlpha). Free fallback: company IR pages, occasional Yahoo coverage. Recent research (arXiv 2511.15214, 2604.13260) shows speaker-identity-aware sentiment beats aggregate.
- **Premium panels** ($2–12M/yr) — credit-card panels (YipitData, Earnest, Facteus), satellite (Orbital Insight, RS Metrics, Spire), app/web (SimilarWeb, Sensor Tower), aggregators (ExtractAlpha, Eagle Alpha, BattleFin, Nasdaq Data Link). Only matters when managing OPM.

For a solo builder: **EDGAR + Reddit + GDELT covers ~80% of the value**.

### Reading list

**Books — the bible:**
1. **Marcos López de Prado, *Advances in Financial Machine Learning* (2018)** — single most-cited modern ML-in-finance text. Required: chapters 3 (triple-barrier labeling), 4 (sample weights), 7 (CPCV), 14 (backtest statistics), 17 (structural breaks).
2. **López de Prado, *Machine Learning for Asset Managers* (2020)** — shorter, focused on portfolio construction, denoised covariance, hierarchical clustering (HRP/NCO).
3. **Stefan Jansen, *Machine Learning for Algorithmic Trading*** + companion repo [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) — 23 chapters of executable notebooks. **Single best free reference repo in the space.**
4. **Gregory Zuckerman, *The Man Who Solved the Market* (2019)** — Renaissance Technologies origin + philosophy.
5. **Ernie Chan, *Algorithmic Trading: Winning Strategies and Their Rationale*** — practical algo-trading, accessible math level.
6. **Robert Carver, *Systematic Trading*** — CTAs, position sizing, systematic frameworks.

**Aggregators / blogs (subscribe):**
- **[Quantocracy](https://quantocracy.com)** — best daily aggregator. Check 2-3×/week.
- **[Alpha Architect](https://alphaarchitect.com)** — academic-paper summaries, factor research.
- **[AQR Insights](https://www.aqr.com/Insights)** — Cliff Asness's library; best public quant fund research.
- **[Newfound Research](https://blog.thinknewfound.com)** — Corey Hoffstein's writing; portable alpha, return stacking.
- **Two Sigma, Jane Street tech blogs** — occasional gems on infrastructure + microstructure.

**Podcasts:**
- **[Flirting With Models](https://www.flirtingwithmodels.com)** (Corey Hoffstein) — best in the space.
- **Acquired podcast — Renaissance Technologies episode (March 2024)** — canonical accessible deep-dive.

**People worth following on X:**
- Marcos López de Prado (@lopezdeprado) — primary feed for ML-in-finance methodology
- Ernie Chan (@echanQT) — practical algo-trading
- Corey Hoffstein (@choffstein) — Newfound; portable alpha, trend
- Cliff Asness (@CliffordAsness) — AQR; combative, often correct on factor decay
- Euan Sinclair (@_eu) — options/vol

**Paper sources:**
- **SSRN Financial Economics Network** — most quant papers land here pre-journal. Bookmark Bailey, López de Prado, Harvey, Liu, Pedersen, Asness author pages.
- **arXiv q-fin** — daily new papers; q-fin.PM (portfolio mgmt), q-fin.ST (statistical finance), q-fin.TR (trading).

---

## Cross-references

- QA's existing roadmap: [roadmap.md](roadmap.md)
- QA bundle format (what stage 5 will consume): [phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md)
- Walk-forward sketch (stage 4): [walk_forward_validation.md](walk_forward_validation.md)
- QC strategy mining (stage 6): [QC's roadmap](../../QuantaQC/docs/roadmap.md)
- QC integration (stage 6 ←→ QA bundle): [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md), [QC phase_11](../../QuantaQC/docs/phase_11_qa_integration.md)
- Auto-publish (partial stage 10): [phase_4_auto_publish.md](phase_4_auto_publish.md)

---

## Open decisions before any code

1. Sibling repo `QuantaResearch` or fold into QA's existing repo as a `quantaresearch/` package?
   - **Recommend separate repo** — keeps QA scoped to factor mining; lets QuantaResearch evolve independently and feed multiple downstream consumers (not just QA).
2. Where do raw ideas live before formalization?
   - **Recommend** local JSON queue files (gitignored), not a database. Move to SQLite if scale demands.
3. How aggressive is the de-dup against QuantaAlphaFindings?
   - Day 1: by hypothesis text similarity (LLM judge).
   - Later: also by factor expression (qlib AST equivalence after formalization).
4. Schedule for daily fetch?
   - Cron / Windows Task Scheduler hitting `scripts/daily_fetch.py` at, say, 06:00. Outputs to a queue file the user reviews.
