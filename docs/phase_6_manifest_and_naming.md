# Phase 6 — Run manifest + display name

Status: ✅ shipped 2026-05-09 (Phase B in the implementation plan)

Each mining run now self-labels and writes an explicit linkage manifest
on completion. History and Models pages show human-friendly names instead
of timestamp IDs.

## Why

QA writes 3 different naming systems to disk in parallel — log dir
(`log/2026-05-08_02-13-32-…`), workspace (`workspace_exp_20260507_211331`),
factor library (`all_factors_library_<suffix>.json`). Before this phase,
the FE showed all three as raw strings with no obvious connection. Users
couldn't tell which workspace produced which run, or which library matched
which workspace.

## What shipped

### Display name on every run

- `MiningStartRequest` accepts optional `displayName: str`
- ChatInput's icon bar exposes a "Run name" field (next to Custom-direction)
- Stored in task config; flows into the manifest at completion

### manifest.json writer (Phase B)

After every successful task completion, [_write_run_manifest](../frontend-v2/backend/app.py)
stamps `log/<run_id>/manifest.json`:

```json
{
  "schema_version": 1,
  "run_id": "2026-05-09_HH-MM-SS-…",
  "display_name": "Q2 vol experiment",
  "objective": "<the user's typed text>",
  "library_suffix": "exp_20260509_HHMMSS",
  "library_name": "all_factors_library_exp_20260509_HHMMSS.json",
  "workspace_name": "workspace_exp_20260509_HHMMSS",
  "started_at": "2026-05-09T...",
  "completed_at": "2026-05-09T...",
  "status": "completed",
  "config": { "numDirections": ..., "maxRounds": ... }
}
```

### Backend linkage inference

[_infer_run_linkages](../frontend-v2/backend/app.py) tries:
1. **Manifest** — explicit pointers (Phase B; for new runs)
2. **Mtime fallback** — picks the workspace whose first parquet was
   written within ±3h of the run's start. Best-effort.

Returned to the FE in `runs/list` and `runs/{id}`:

```json
{
  "linked_workspace": "workspace_exp_…",
  "linked_library":   "all_factors_library_….json",
  "linkage_source":   "manifest" | "mtime" | null,
  "display_name":     "...",
  "objective":        "..."
}
```

### FE updates

- History list cards: `display_name` is the title; date is subtext;
  raw `run_id` is small mono caption
- History detail header: same hierarchy, plus the original `objective`
  rendered as italic quote
- Workspace dropdown in Models > Build new: shows linked library

### Reusable NamingGuide

Shipped a small disclosure component used on History + Models pages:
"What do these names mean?" — explains log dir vs workspace vs library.

## Acceptance

- New run with display_name "Foo" → History card shows "Foo" as the
  title, with date below
- `manifest.json` exists after the run completes; reading it gives
  workspace + library back
- Detail view shows "Workspace: …" + "Library: …" badges with a mtime
  warning if no manifest exists

## Limitations

- **Legacy runs**: runs that completed before Phase 6 don't have a
  manifest. Mtime fallback works only if the workspace happened within
  ±3h. For older mismatched runs, no link is shown. **Phase 8 fixes
  this** with a backfill script.
- **In-flight visibility**: the manifest is written at *completion*. While
  a run is in progress, History shows it via mtime correlation only. Live
  display_name during a run is shown via the in-memory task on the
  Mining Dashboard.
