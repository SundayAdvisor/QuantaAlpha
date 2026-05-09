# Phase 8 — Legacy run backfill

Status: 📋 sketch — not built. ~1 hour of work.

## Why

Phase 6 stamps a `manifest.json` into every NEW run's log dir. But runs
completed before Phase 6 don't have one. The `_infer_run_linkages`
mtime-correlation fallback works when log/workspace timestamps are within
±3h, but for the user's existing 2026-05-08 run (log) vs 2026-05-07
workspaces (~14 hours earlier — different mining session), it returns
nothing.

History therefore shows blank linkage chips on legacy runs. Cosmetic, not
broken — but ugly.

## What to build

A small one-shot script + optional auto-on-startup:

```python
# scripts/backfill_run_manifests.py
"""
Reverse-engineer manifest.json for legacy QA runs.

For each log/<run_id>/ that doesn't have a manifest.json:
  1. Read trajectory_pool.json + evolution_state.json (already there)
  2. Find the workspace whose first parquet write was nearest in time
     (within ±24h instead of ±3h since legacy data is messier)
  3. Look up the matching all_factors_library_<suffix>.json by
     workspace name suffix
  4. Write a manifest.json with linkage_source="backfill" so we can
     distinguish from real-time-stamped manifests

Usage:
    .venv/Scripts/python.exe scripts/backfill_run_manifests.py           # all runs missing manifests
    .venv/Scripts/python.exe scripts/backfill_run_manifests.py --run X   # one specific
    .venv/Scripts/python.exe scripts/backfill_run_manifests.py --dry-run # report only
"""
```

Hook into `_infer_run_linkages` to surface the new source value:

```python
# When linkage_source == "backfill", the FE shows an amber "inferred" chip
# (same as today's "mtime") plus a tooltip "backfilled YYYY-MM-DD"
```

## Open decisions

- **Auto-run on backend startup?** Pro: instant cleanup of legacy data.
  Con: opaque side effect on startup. Recommend: explicit script for now;
  add a "Backfill manifests" button to Settings if it gets requested.
- **Window**: ±24h or ±48h? Legacy QA data on this machine is 2026-05-07
  workspaces vs 2026-05-08 logs — fits ±24. Anything more is a different
  mining session masquerading as the same one.
- **Conflict resolution**: if a run has multiple plausible workspaces, pick
  the one with most parquets (that's the "main" iteration), not just the
  closest mtime.

## Acceptance

- Run `backfill_run_manifests.py` on the live `log/` dir → produces N
  manifests where N = (legacy runs without manifests AND with a workspace
  match within ±24h)
- Refresh History → previously-blank linkage chips now populate, with a
  small tooltip "backfilled" so it's clear the link was inferred not
  recorded
- Newly-completed runs (Phase 6 manifest writer) are NOT touched by the
  script

## Trigger to actually build

Build this when:
- You've accumulated enough legacy runs that the blank linkage chips on
  History are annoying, OR
- A user (you) asks "where's the workspace for run X?" and the answer
  has to be "go grep mtimes manually"

Until then it's noise.

## File-level deliverables

```
scripts/backfill_run_manifests.py    new
                                     reads log/ + data/results/, writes manifests
                                     into each missing log/<id>/manifest.json
frontend-v2/backend/app.py           tiny: extend linkage_source enum to include
                                     "backfill" so FE can render distinct tooltip
frontend-v2/src/types/index.ts       extend `linkage_source` union type
frontend-v2/src/pages/RunHistoryPage.tsx
                                     show "backfilled" tooltip variant on the
                                     amber inferred chip
```

## Cross-references

- The manifest schema this script produces: see [phase_6_manifest_and_naming.md](phase_6_manifest_and_naming.md)
- Why the linkage problem exists in the first place: workspace ↔ library
  uses YYYYMMDD format, log dir uses YYYY-MM-DD with microseconds — see
  the inline NamingGuide component for the user-facing explanation
