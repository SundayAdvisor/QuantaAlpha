# QuantaAlpha — Changelog & Status Tracker

## 2026-05-09 (latest+4) — Math-heavy methods reference doc

User asked if the docs covered math-heavy research. Honest answer was:
partial — scattered across phase 13/15/16 and a small table in
research_pipeline.md, but no dedicated treatment.

Wrote [docs/math_heavy_methods.md](math_heavy_methods.md) — a practical
reference covering 12 method families with intuition (no notation
overload), library + code sketch, and connection to QA's pipeline
per technique:

  1. Statistical-significance: Deflated Sharpe, multiple-testing
     correction (Bonferroni / BH), Combinatorial Purged CV
  2. Time-series structure: HMM, Kalman, cointegration / Johansen, GARCH
  3. Information theory: mutual information, transfer entropy
  4. Causal inference: Pearl do-calculus, Rubin potential outcomes,
     LdP's Causal Factor Investing
  5. Stochastic calculus / pricing — minimal section for non-options
     shop, points at Hull/Wilmott if needed later
  6. Random matrix theory — Marchenko-Pastur, denoising covariance,
     HRP for portfolio construction
  7. Signal extraction — Fourier, wavelets, EMD
  8. Distributional robustness — CVaR, DRO
  9. Triple-barrier labeling (LdP)
  10. Fractional differencing (LdP) — preserves long memory
  11. Meta-labeling (LdP) — two-stage classifier for trade selection
  12. Statistical learning theory — overfitting bounds

Plus a section on how LLM-driven mining + math methods complement each
other (LLM = generative diversity; math = rigor; together = structured
search with rigor) and a recommended reading order (LdP AFML/MLAM,
Stefan Jansen's repo, Hamilton, Bishop).

Reference doc, not a build phase. Linked from roadmap.md as a 📚 row.

## 2026-05-09 (latest+3) — Phases 18-19 specs (sibling-team patterns adopted)

User asked which of the QuantaAlpha team's other publications are worth
adopting. Researched the 33-publication portfolio at quantaalpha.com +
GitHub org. Three candidates surfaced; specs written for the two worth
building.

**Phase 18 — Factor memory service (MemGovern-inspired)** — 📋 next-up
Adopts arXiv 2601.06789 (ACL 2026) pattern: factor pool becomes a
standalone HTTP service on :8002 (ChromaDB + SQLite), exposes 2 LLM
tools (`/search_factor_experience`, `/get_factor_card`). LLM calls
search BEFORE proposing a factor → stops re-discovering near-duplicates
across iterations. Includes the curated-card schema (hypothesis,
mechanism, decision, lessons learned, embedding) + curation step that
distills feedback_details into a clean card. ~1-2 days. Highest ROI of
the new entries; user already observed the live mining run is proposing
3 closely-related "vol-conditional reversal" factors in round 0 alone —
this directly fixes that mode.

**Phase 19 — Slot-based mutation (EvoControl-inspired)** — 📋 sketch
Adopts arXiv 2601.07348 pattern: define explicit slots in factor
expressions (window / feature / transform / normalization / binary_op),
mutate ONE slot at a time instead of regenerating the whole expression.
Plus diversified-init enforcer (round 0 factors must have distinct
slot signatures) + combinatorial sweep on promoted factors. Claims
30-80% iteration reduction. ~3-5 days, queue after 18.

**SE-Agent deliberately NOT adopted for QA.** arXiv 2508.02085 governs
multi-step agent trajectories (where each trajectory has many
intermediate LLM-as-actor states). QA's trajectories are flat-ish
(hypothesis → expression → backtest → feedback as one shot). Better
fit for QC's multi-step strategy lifecycle; flagged for QC's future
roadmap entry.

Roadmap + research_pipeline.md updated with new rows + the SE-Agent
deferral rationale.

## 2026-05-09 (latest+2) — Phase docs 13-17 created (next-up build queue)

The research_pipeline.md sections "Step 0/1/3" + "Renaissance principles"
were promoted into 5 dedicated phase specs so each is followable instead
of buried. Each doc has its own scope / file-level deliverables /
acceptance criteria / cross-references.

**New phase docs (all 📋 sketch — no code yet)**

- [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md) —
  4-fix bundle for the factor admission gate: Deflated Sharpe Ratio
  (selection bias correction), Combinatorial Purged CV (label-overlap
  leakage fix), triple-barrier labeling (better than fixed-horizon
  labels), AST-similarity dedup (steals AlphaAgent's regularizer to
  prevent iter-11/12 mode collapse). ~1 day total. **Highest-ROI next
  step.**

- [phase_14_quantaresearch.md](phase_14_quantaresearch.md) — new sibling
  project layout: arXiv/Semantic Scholar/NBER/Quantocracy crawlers,
  LLM hypothesis formalizer with full prompt sketch, data-readiness
  pre-flight, novelty dedup vs QuantaAlphaFindings, auto-feed to QA's
  mining/start. ~1-2 days for v1. Replaces "user types objective" with
  "system proposes from current academic flow."

- [phase_15_hmm_regime_layer.md](phase_15_hmm_regime_layer.md) — Renaissance-
  flavored HMM regime detection with hmmlearn. Includes a 7×3 strategy-
  to-regime mapping matrix (which strategy types work in calm/normal/
  turbulent regimes), code sketch for the detector, qlib feature wiring
  to expose `$regime` to factor expressions, validation plan, caveats
  about look-ahead bias and regime-of-regimes. ~half day standalone.

- [phase_16_signal_stacking.md](phase_16_signal_stacking.md) — explicit
  Renaissance signal-stacking architecture. 4 layers: (A) 5 combiners
  benchmarked side-by-side (equal-weight / IC-weighted / inverse-var /
  LightGBM / HRP), (B) per-factor contribution attribution, (C) regime-
  conditional fits using Phase 15, (D) online weight refresh. Includes
  the 1+(N-1)c portfolio math showing why N=20 weak signals at c=0.3
  beats any single signal. ~2-3 days for layers A+B; C blocked on 15;
  D blocked on live history.

- [phase_17_continuous_redevelopment.md](phase_17_continuous_redevelopment.md) —
  answers "Renaissance retrains every 2yr; should we?". Currently we
  train 2008-2015 (ZIRP-era data, deployment-stale). Phase 17 ships 4
  training-window presets in the FE Advanced panel: paper-aligned,
  recent-regime (2018-22 / 23 / 24-26 — recommended for deployment),
  stress-test (covers COVID + bear), walk-forward (slow, gated by 13).
  Plus a `compare_bundles.py` A/B harness. ~half day.

**Roadmap updated**

[roadmap.md](roadmap.md) gets 5 new rows (phases 13-17) + the "what's
next" order updated to: 9 → 13 → 17 → 15 → 14 → 16 → … (existing 8/10/11).

**research_pipeline.md updated**

The "Recommended build sequence" section is now a single index table
pointing at the new phase docs instead of inline write-ups, so it stays
short and the depth lives in dedicated specs. Sections on Renaissance
principles, ecosystem references, and reading list remain unchanged in
research_pipeline.md.

## 2026-05-09 (latest+1) — Research pipeline doc enriched with 2024-26 quant ecosystem survey

**Updated** [docs/research_pipeline.md](research_pipeline.md):

- New "Renaissance principles worth borrowing" section: 5-row table
  mapping their public methodology (signal stacking / HMM regime detection
  / 2-yr model lifecycle / cointegration / intraday HFT) to our stack —
  what we do already, what to add, what's not replicable.
- New "Step 0 — Statistical-rigor upgrades" at the top of the build
  sequence: highest-ROI items from López de Prado's *Advances in Financial
  Machine Learning* — Deflated Sharpe Ratio, Combinatorial Purged CV,
  triple-barrier labeling, AST-similarity dedup. ~1 day total, biggest
  near-term impact on factor-mining honesty. Should ship before any
  other new stages.
- Added Step 3 (HMM regime layer, ~50 lines hmmlearn) and Step 5
  (FinBERT sentiment on EDGAR 8-Ks) to the sequence.
- New "Reference reading & open-source ecosystem" section covering:
  * 11 LLM-in-quant frameworks ranked verdict (RD-Agent, AlphaAgent,
    TradingAgents, FactorMAD, AlphaSAGE, FinGPT, FinBERT, FinMem, FinRL,
    FinRobot, Alpha-R1) with GitHub URLs
  * Classical ML state of 2025 (LightGBM/XGBoost/CatBoost, TFT, N-BEATS,
    Mamba/SSM with citations)
  * Math foundations table (HMM, Kalman, Johansen, MI, DSR, CPCV, causal)
  * Backtest framework comparison (qlib, Lean, vectorbt, NautilusTrader,
    RiskFolio-Lib, skfolio, alphalens-reloaded, quantstats)
  * Alt-data sources free vs paid (EDGAR + GDELT + Reddit free tier
    covers ~80%; premium panels not worth it for solo builders)
  * Reading list: López de Prado canon (AFML, MLAM, Causal), Stefan
    Jansen's ML4Trading repo, Zuckerman's Renaissance book, plus
    aggregators (Quantocracy, AQR, Alpha Architect), podcasts (Flirting
    With Models, Acquired RT episode), and people-to-follow on X.

This is reference material, not a build commitment. Use as the index
to consult when picking what to add next.

## 2026-05-09 (latest) — Full research pipeline plan documented

**Sketched (planned, not built)**

- [docs/research_pipeline.md](research_pipeline.md) — comprehensive plan
  for the surrounding "real quant" 10-stage workflow: idea sourcing
  (arXiv + Semantic Scholar + NBER), hypothesis formalization, data
  readiness check, risk decomposition (Fama-French residual alpha),
  decay monitoring, knowledge persistence. Maps each stage to its current
  status (built / sketched / missing), proposes a new sibling project
  `QuantaResearch` for stages 0/1/2, sketches the architecture diagram
  end-to-end, and gives a recommended build sequence (1–2 days each for
  the highest-leverage missing pieces). Linked from `roadmap.md` as
  the "★ Full research pipeline" entry.
- Honest scope: this is months-of-work end-to-end. The doc breaks it
  into ~5 person-days of high-leverage work (stages 0, 1, 2, 5) plus
  longer-horizon stages 9 + 10 deferred until live deployment exists.

## 2026-05-09 (later) — Self-describing factor publishing

**Shipped**

- `scripts/publish_findings.py` — `factor.json` now carries the full LLM
  rationale (`hypothesis_details`), post-backtest analysis (`feedback_details`),
  denormalized parent records (so consumers see parent's hypothesis +
  expression + metrics inline), and the executable Python code for each
  factor. `spec.md` rewritten to expose the LLM rationale + factor code
  blocks + "What we learned" + lineage. See [phase_4_auto_publish.md](phase_4_auto_publish.md)
  for the full output schema.
- `extract_production_model.py` — bundled `factor_expressions.yaml` now
  includes hypothesis + LLM rationale + parent IDs + per-factor metrics
  (not just expression). The bundle is now self-describing for downstream
  use (phase 11 QC integration).
- Reasoning: a published factor without its hypothesis + LLM rationale +
  what-we-learned is just a formula. Bundle without the same is a black
  box for whoever consumes it. Carrying this context across the boundary
  is what makes the QC LLM able to reason about WHEN a factor works,
  not just compute it.



A running record of what's been built, in reverse chronological order, plus
"what's next" at the bottom. Read this if you want a fast catch-up after
being away from the project.

For deep dives on any item, follow the doc links to the phase specs.

---

## 2026-05-09 — Universe-aware mining + phase docs reorganization

**Shipped**

- **Universe-aware mining** — QA can now mine on sp500 / nasdaq100 / commodities
  / a custom ticker list. Per-run train/valid/test date overrides. LLM-based
  universe auto-pick from objective text. New FE "Advanced" panel on home
  page chat input. Spec: [phase_7_universe_aware_mining.md](phase_7_universe_aware_mining.md)
- **Three universes fresh through 2026-05-07**:
  - sp500: 547/745 tickers fresh (rest delisted/acquired)
  - nasdaq100: 164/283 tickers fresh
  - commodities: 13/13 — gold/silver/oil/gas/broad ETFs (NEW)
- **Run manifest + display name** — every new mining run writes `manifest.json`
  with explicit linkage to its workspace + factor library. History page
  shows display_name as primary title. Spec: [phase_6_manifest_and_naming.md](phase_6_manifest_and_naming.md)
- **Settings overhaul** — API tab now reflects active LLM provider (Claude
  Code) instead of pretending it's an API-key path. CSI markets removed.
  Parallel-directions max bumped to 20. Friendlier unsaved-changes banner.
  Research Directions tab gets an explainer. Part of [phase_3_llm_ux.md](phase_3_llm_ux.md)
- **Home page info panel rewrite** — accurately reflects mining splits;
  amber callout that "test is in-sample for the mining loop"; green
  callout marking 2020-11-11 → 2026-05-07 as genuine OOS
- **Doc reorganization** — added [roadmap.md](roadmap.md) + phase docs
  modeled on QuantaQC's structure. Existing scattered docs unchanged but
  now linked from the roadmap.
- **CHANGELOG.md** (this file)
- **[data_setup.md](data_setup.md)** — how to fetch / refresh qlib data via
  the script, with cookbook for common scenarios

**Sketched (planned, not built)**

- [phase_8_legacy_run_backfill.md](phase_8_legacy_run_backfill.md) — script
  to reverse-engineer manifests for older runs. ~1 hr.
- [phase_9_smoke_run.md](phase_9_smoke_run.md) — first end-to-end run that
  produces a non-baseline factor-trained bundle. **Highest-value next step.**
- [walk_forward_validation.md](walk_forward_validation.md) — three options
  documented; build only if phase 9 shows in-sample bias is hurting deployment.

---

## 2026-05-09 (earlier) — LLM-driven UX bundle (Phase 3)

**Shipped** ([phase_3_llm_ux.md](phase_3_llm_ux.md) covers all of this)

- **Run History page** — per-run view (separate from the per-factor Factor
  Library). Friendly date + linkage chips + workspace/library badges
- **AI verdict** — "Analyze" button on a History run calls LLM, returns
  verdict ∈ {robust, promising, regime-fit, marginal, broken}, cached
- **Lineage graph** — SVG-based parent → child mutation/crossover diagram
- **Objective Suggester** — home-page panel with 8 strategies (auto/gap-fill/
  adventurous/refinement/diversify/focused/contrarian/simplify/compose) +
  topic chips (Momentum/Value/Volatility/etc) prefilling the focus hint
- **Production Models tab** — list bundles + Build new (workspace dropdown
  + run-name + mode) + live build log
- **NamingGuide component** — inline disclosure explaining the three QA
  naming systems (log dir / workspace / factor library)
- **Metric Reference card** on History — explains RankICIR / IR thresholds
  + how the app uses them
- Backend asyncio fix: LLM endpoints now run in `asyncio.to_thread()` so
  Claude Code SDK doesn't collide with FastAPI's event loop

---

## 2026-05-09 — Auto-publish to QuantaAlphaFindings

**Shipped** ([phase_4_auto_publish.md](phase_4_auto_publish.md))

- `scripts/publish_findings.py` — applies hard gates (RankICIR > 0.05,
  IR > 0, MDD > -40%, top_n=5) and writes factor.json + spec.md +
  results.md + provenance.json per published factor
- Auto-trigger on mining task completion (`_auto_publish_qa_run`)
- Resolver finds findings repo at sibling `QuantaAlphaFindings/`
  (CamelCase) or `quantaalpha-findings/` (lowercase) or `$QA_FINDINGS_REPO`
- Cloned the (initially empty) `https://github.com/SundayAdvisor/QuantaAlphaFindings.git`

---

## (earlier 2026-05-07/08) — Phase 5/6 model persistence

**Shipped** ([phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md))

- `extract_production_model.py` — train fresh LightGBM on gate-passing
  factors from a workspace, save bundle (model.lgbm + factor_expressions.yaml
  + extraction_conf.yaml + metadata.json)
- `predict_with_production_model.py` — load bundle, run predictions on
  any date range, output CSV
- Two existing bundles on disk (smoke_test_baseline + _v2) — both
  baseline-only (`num_factors_in_metadata: 0`)

---

## What's NEXT (in suggested order)

1. **Phase 9 — End-to-end smoke run** ← highest-value
   Spec: [phase_9_smoke_run.md](phase_9_smoke_run.md)

   Take an existing (or fresh) mining run → extract a factor-trained
   bundle (not baseline) → predict on 2020-11-11 → 2026-05-07 → measure
   IC/RankICIR. Confirms phases 1-7 actually work as a pipeline. ~1-3
   hours including waiting.

2. **Phase 8 — Legacy run backfill**
   Spec: [phase_8_legacy_run_backfill.md](phase_8_legacy_run_backfill.md)

   Cosmetic but cheap — reverse-engineer manifests for old runs. ~1 hr.
   Defer until phase 9 lands.

3. **Phase 11 — QC integration (QAAlphaModel)**
   Spec in this repo: [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md)
   Spec in QC: [QC's phase_11_qa_integration.md](../../QuantaQC/docs/phase_11_qa_integration.md)

   Has its own multi-step plan (11.0/11.A/11.B/11.C/11.D). Don't start
   until phase 9 produces a real factor-trained bundle to feed in.

4. **Phase 10 — Walk-forward validation** (only if phase 9 reveals overfit)
   Spec: [walk_forward_validation.md](walk_forward_validation.md)

   Three options documented; ship Option A first (anchored split + holdout)
   when needed.

5. **Phase 12 — Future expansions** (low priority, opportunistic)
   - More universes: DJIA, sector ETFs, FX, R2K
   - Fresh-data inference (predict tomorrow without re-mining)
   - Multi-model ensembles
   - Auto-retraining cadence

---

## How to update this file

When you ship a phase or change something user-visible:

```
## YYYY-MM-DD — Short title

**Shipped**
- Bullet list with file/spec links

**Sketched (planned, not built)**
- ...
```

The "What's NEXT" section at the bottom should be re-ordered each time
your priorities change. The roadmap.md is the structural index; this
CHANGELOG.md is the time-ordered narrative.
