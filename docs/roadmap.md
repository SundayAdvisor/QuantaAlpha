# QuantaAlpha Roadmap

The phase index. Each phase has its own spec doc when it's nailed down
enough to build. This file is the source of truth for "what's done / what's
next."

Legend: ✅ shipped · 🔨 building · 📋 sketch (designed, not built) · 💭 future (idea, no spec yet)

| # | Title | Status | Spec |
|---|---|---|---|
| 1 | Mining loop (paper-shape: planning → factor gen → backtest → evolution) | ✅ shipped | inherited from rdagent — see [paper_replication.md](paper_replication.md), [experiment_guide.md](experiment_guide.md) |
| 2 | Frontend v2 (React + Vite + Tailwind) | ✅ shipped | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) §frontend-v2 |
| 3 | LLM-driven UX — Run History, AI verdict, lineage graph, Objective Suggester, Production Models tab, Settings overhaul | ✅ shipped | [phase_3_llm_ux.md](phase_3_llm_ux.md) |
| 4 | Auto-publish to QuantaAlphaFindings (gate-passing factors → public repo) | ✅ shipped | [phase_4_auto_publish.md](phase_4_auto_publish.md) |
| 5 | Model persistence — extract LightGBM bundles + predict on new dates (Phase 5/6) | ✅ shipped | [phase_5_6_and_quantconnect.md](phase_5_6_and_quantconnect.md) |
| 6 | Run manifest + display name (mining runs labelled, History shows linked workspace + library) | ✅ shipped | [phase_6_manifest_and_naming.md](phase_6_manifest_and_naming.md) |
| 7 | Universe-aware mining — sp500 / nasdaq100 / commodities / custom tickers + per-run date splits + LLM auto-pick | ✅ shipped | [phase_7_universe_aware_mining.md](phase_7_universe_aware_mining.md) |
| 8 | mtime → manifest backfill for legacy runs (older runs get reverse-engineered linkage) | 📋 sketch | [phase_8_legacy_run_backfill.md](phase_8_legacy_run_backfill.md) |
| 9 | End-to-end smoke run on real factor-trained bundle (validate Phase 5/6 produces a non-baseline bundle that beats the baseline) | 📋 next | [phase_9_smoke_run.md](phase_9_smoke_run.md) |
| 10 | Walk-forward validation (replace fixed train/valid/test with rolling K-fold or anchored split + holdout) | 📋 sketch | [walk_forward_validation.md](walk_forward_validation.md) |
| 11 | QC integration — QAAlphaModel consumes QA bundles inside QuantConnect strategies | 📋 sketch | [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md), QC's [phase_11_qa_integration.md](../../QuantaQC/docs/phase_11_qa_integration.md) |
| 12 | Future — more universes (DJIA, sector ETFs, FX), fresh-data inference (predict tomorrow without re-mining), multi-model bundles, retraining cadence | 💭 future | _(no spec yet)_ |
| **13** | **Admission gate upgrades** — Deflated Sharpe Ratio + Combinatorial Purged CV + triple-barrier labels + AST-novelty dedup. Highest-ROI honesty fix. ~1 day. | 📋 next-up | [phase_13_admission_gate_upgrades.md](phase_13_admission_gate_upgrades.md) |
| **14** | **QuantaResearch (idea sourcing)** — new sibling project: arXiv crawler + LLM hypothesis formalizer + data-readiness check + auto-feed into QA. Replaces "user types objective" with "system proposes from academic flow." ~1-2 days. | 📋 sketch | [phase_14_quantaresearch.md](phase_14_quantaresearch.md) |
| **15** | **HMM regime detection** — Renaissance-style 3-state hidden Markov model on SPY (calm / normal / turbulent). Exposed as `$regime` qlib feature + strategy-execution gate. Includes per-regime strategy mapping. ~half day. | 📋 next-up | [phase_15_hmm_regime_layer.md](phase_15_hmm_regime_layer.md) |
| **16** | **Signal stacking** — explicit alpha combiner: 5 combiner functions (equal-weight / IC-weighted / inverse-var / LightGBM / HRP) benchmarked side-by-side, per-factor contribution attribution, regime-conditional fits, online weight refresh. The Renaissance principle as code. ~2-3 days. | 📋 sketch | [phase_16_signal_stacking.md](phase_16_signal_stacking.md) |
| **17** | **Continuous redevelopment / training cadence** — answer to "Renaissance retrains every 2yr; should we?". 4 training-window presets (paper-aligned / recent-regime / stress-test / walk-forward) in FE Advanced panel + bundle A/B compare harness. ~half day for v1. | 📋 next-up | [phase_17_continuous_redevelopment.md](phase_17_continuous_redevelopment.md) |
| **18** | **Factor memory service** — adopt MemGovern's (arXiv 2601.06789) pattern: factor pool becomes a queryable HTTP service on :8002 + 2 LLM tools (`/search_factor_experience`, `/get_factor_card`) so the LLM stops re-discovering failed factors every iteration. Curated cards, not raw history. ~1-2 days. | 📋 next-up | [phase_18_factor_memory_service.md](phase_18_factor_memory_service.md) |
| **19** | **Slot-based mutation** — adopt EvoControl's (arXiv 2601.07348) pattern: define explicit slots (window / feature / transform / normalization / binary_op) in factor expressions, mutate one slot at a time instead of full-expression rewrite. Plus diversified initialization + combinatorial sweep on promotion. Claims 30-80% iteration reduction. ~3-5 days. | 📋 sketch | [phase_19_slot_based_mutation.md](phase_19_slot_based_mutation.md) |
| ★ | **Full research pipeline** — the "real quant" 10-stage workflow surrounding QA + QC (idea sourcing, hypothesis formalization, data readiness, risk decomposition, decay monitoring, knowledge persistence). Spans this repo + a proposed sibling `QuantaResearch` + QC. **Index document** — phases 13-17 are the buildable pieces. | 📋 plan | [research_pipeline.md](research_pipeline.md) |

## Order of operations (the "what's next" recommendation)

```
Today:                          ✅ phases 1–7 shipped

Suggested next, in order:
  → phase 9   (1–3 hrs)         smoke-run a real factor-trained bundle on
                                an existing mined workspace. Confirms the
                                whole pipeline 1–7 actually works end-to-end
                                with non-trivial data.

  → phase 13  (~1 day)          admission gate upgrades — DSR + CPCV +
                                AST-novelty dedup. Cheapest, highest-impact
                                honesty fix. Ship before any new stages.

  → phase 17  (~half day)       training-window presets in FE Advanced —
                                lets us A/B paper-aligned vs recent-regime
                                without code changes per run.

  → phase 15  (~half day)       HMM regime detection. Renaissance-style.
                                Standalone — feeds phase 16.

  → phase 14  (1–2 days)        QuantaResearch idea sourcer. Auto-feed
                                arXiv-derived hypotheses into QA mining.

  → phase 16  (2–3 days)        signal stacking — explicit alpha combiner.
                                Builds on 13 + 15.

  → phase 18  (1–2 days)        factor memory service (MemGovern-style).
                                Stops LLM rediscovering failed factors.

  → phase 19  (3–5 days)        slot-based mutation (EvoControl-style).
                                30-50% iteration reduction. After 18.

  → phase 8   (~1 hr)           backfill linkage for older runs. Cosmetic.

  → phase 10  (3–5 hrs option-A) walk-forward — only worth it after 13
                                lands (CPCV is the foundation).

  → phase 11  (5–7 days, multi-step) QC integration. Defer until you have
                                a factor-trained bundle to feed in (phase 9).

  → phase 12  (anytime)         more universes / inference / retraining.
                                These are loose; pick what's blocking you.
```

## What's intentionally out of scope right now

- **Live / paper trading deployment** — assumed via QC integration (phase 11), not a separate phase
- **Model registry** (MLflow / DVC) — file-based bundles are fine for two users
- **Auto-retraining cadence** — manual swap is fine; revisit after phase 11 lands
- **Multi-bundle ensembles** — one bundle = one model for v1; ensemble is phase 12

## How to read this file going forward

- A phase moves to ✅ when its spec doc says "Acceptance criteria met" AND the relevant code is on `windows-claude-code` branch
- New work goes through: 💭 → 📋 (write the spec) → 🔨 (build) → ✅ (ship)
- If you find the doc disagrees with the code, the code wins — please open an issue or just fix the doc

## Cross-repo notes

- This roadmap covers QuantaAlpha. The sister project QuantaQC has its own [roadmap.md](../../QuantaQC/docs/roadmap.md). The two intersect at phase 11 (QC consumes QA bundles).
- Findings published to [QuantaAlphaFindings](https://github.com/SundayAdvisor/QuantaAlphaFindings) are documented in phase 4.
- The integration architecture between QA and QC is in [qc_multi_strategy_architecture.md](qc_multi_strategy_architecture.md).
