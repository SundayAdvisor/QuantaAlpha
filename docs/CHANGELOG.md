# QuantaAlpha — Changelog & Status Tracker

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
