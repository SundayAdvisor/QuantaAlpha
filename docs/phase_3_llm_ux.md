# Phase 3 — LLM-driven UX

Status: ✅ shipped 2026-05-09

Bundles all the LLM- and history-related FE/backend work that landed in
the same arc. Each piece is self-contained but they share components
(types, api client, the AnalysisCard verdict taxonomy) so they're grouped.

## What shipped

### A. Run History (per-run view, not per-factor)

- New nav tab **History** between *Factor Mining* and *Factor Library*.
- Lists every past mining run from `log/` with friendly date + best
  RankICIR + best IR + linked workspace/library chips.
- Selecting a run shows: summary card (with display name + objective),
  AI verdict card (lazy — only computed on click), parent→child lineage
  graph, Metric Reference card (RankICIR / IR thresholds + how the app
  uses them).

Files: [src/pages/RunHistoryPage.tsx](../frontend-v2/src/pages/RunHistoryPage.tsx),
backend endpoints `GET /api/v1/runs/list`, `GET /api/v1/runs/{id}`,
`GET /api/v1/runs/{id}/lineage`, helpers
[quantaalpha/data/run_history.py](../quantaalpha/data/run_history.py).

### B. AI verdict (LLM run analysis)

- Per-run "Analyze" button calls `POST /api/v1/runs/{id}/explain`.
- Backend builds a heuristic pre-verdict from the trajectory pool, then
  asks the LLM to refine it. Verdict ∈ {robust, promising, regime-fit,
  marginal, broken}. Result cached to `log/<run_id>/analysis.json`.
- Surfaces curve-fit smell: positive RankICIR + negative IR → regime-fit.

Files: [quantaalpha/pipeline/analysis.py](../quantaalpha/pipeline/analysis.py),
[src/components/AnalysisCard.tsx](../frontend-v2/src/components/AnalysisCard.tsx).

### C. Lineage graph

- SVG-based parent→child diagram. Columns = directions, rows = rounds.
  Edges colored by child phase (mutation/crossover). No external graph
  lib (we considered react-flow, didn't add the dep).

Files: [src/components/LineageGraph.tsx](../frontend-v2/src/components/LineageGraph.tsx),
endpoint `GET /api/v1/runs/{id}/lineage`.

### D. Objective Suggester

- Home-page panel "Need a starting point?" — LLM proposes 4
  factor-mining directions per click. Topic chips above + Customize
  disclosure for strategy modes (auto/gap-fill/adventurous/refinement/
  diversify/focused/contrarian/simplify/compose).
- Auto-mode picks based on history (no past runs → adventurous; 1 winner
  → refinement; 2+ winners → compose; 5+ runs no winners → contrarian).

Files: [quantaalpha/pipeline/objective_suggester.py](../quantaalpha/pipeline/objective_suggester.py),
[src/components/ObjectiveSuggester.tsx](../frontend-v2/src/components/ObjectiveSuggester.tsx),
endpoint `POST /api/v1/suggest-objectives`.

### E. Production Models tab

- New nav tab **Models** with two sub-tabs:
  - **Bundles**: lists `production_models/` directory, shows metadata +
    factor count + test IC/RIC, lets user inspect factor expressions.
  - **Build new**: form to launch `extract_production_model.py` against
    a chosen workspace + bundle name + mode (full vs baseline-only).
    Live log streamed in.

Files: [src/pages/ProductionModelsPage.tsx](../frontend-v2/src/pages/ProductionModelsPage.tsx),
endpoints `GET /api/v1/bundles/list`, `POST /api/v1/bundles/build`, etc.

### F. Settings overhaul

- API tab surfaces active LLM provider (Claude Code) instead of pretending
  it's an API-key path. API-key fields collapse to fallback config.
- Default market dropdown: removed CSI options (no CN data); only SP500
  shown with note about future expansion.
- Parallel-directions max bumped 10 → 20 with clarifying hint text.
- Unsaved-changes banner: friendlier (info icon, blue) instead of alarming.
- Research Directions tab: explanatory header clarifying it's only used
  when the home-page "Custom research direction" toggle is on, and that
  selecting more presets doesn't improve mining quality.

Files: [src/pages/SettingsPage.tsx](../frontend-v2/src/pages/SettingsPage.tsx).

### G. NamingGuide reusable component

- Inline disclosure on History + Models pages explaining the three QA
  naming conventions (log dir / workspace / factor library) and how
  they relate.

File: [src/components/NamingGuide.tsx](../frontend-v2/src/components/NamingGuide.tsx).

## Why this all shipped together

The prerequisite for B/C/E was A (`run_history.py` + run-list endpoint),
and they share the FE service-layer types + auto-pick smart defaults
([backend's asyncio.to_thread fix](../frontend-v2/backend/app.py)). Doing
them as one phase avoided rework.

## Acceptance

- All seven sub-features render in the live FE
- Backend endpoints all return real data on the existing 2026-05-08 run
- Suggester returns 3+ ideas across multiple style modes
- AI verdict renders for the existing run and caches to disk
