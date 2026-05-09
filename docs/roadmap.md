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

## Order of operations (the "what's next" recommendation)

```
Today:                          ✅ phases 1–7 shipped

Suggested next, in order:
  → phase 9   (1–3 hrs)         smoke-run a real factor-trained bundle on
                                an existing mined workspace. Confirms the
                                whole pipeline 1–7 actually works end-to-end
                                with non-trivial data.

  → phase 8   (~1 hr)           backfill the linkage for older runs. Cheap
                                quality-of-life. Defer until phase 9 lands.

  → phase 10  (3–5 hrs option-A) walk-forward — only worth it once phase 9
                                shows in-sample bias is hurting deployment
                                decisions.

  → phase 11  (5–7 days, multi-step) QC integration. Has its own
                                checkpoint plan. Defer until you have a
                                factor-trained bundle to feed in (phase 9).

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
