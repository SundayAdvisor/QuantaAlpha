# Phase 7 — Universe-aware mining

Status: ✅ shipped 2026-05-09

Mining can now run on multiple universes (sp500, nasdaq100, commodities,
or a custom ticker list), with per-run train/valid/test date overrides,
plus an LLM-based universe auto-pick step.

## Why

Before Phase 7, every run hardcoded SP500 in [conf_baseline.yaml:14](../quantaalpha/factors/factor_template/conf_baseline.yaml).
You could type "mine gold factors" and it'd still mine SP500. Date
splits also had to be edited by hand in the YAML.

## What shipped

### Three universes, all fresh through 2026-05-07

| Universe | Tickers | Notes |
|---|---|---|
| sp500 | 547 fresh / 745 instruments | Default; recently extended via `fetch_qlib_data.py --universe sp500` |
| nasdaq100 | 164 fresh / 283 instruments | Recently extended |
| commodities | 13 / 13 | New — gold/silver/oil/gas ETFs (GLD, IAU, GDX, GDXJ, SLV, SIVR, PPLT, USO, UNG, DBC, DBA, GSG, PDBC) |

(*"fresh" = data through 2026-05-07; the rest are tickers that delisted
or got acquired post-2020 and didn't survive the yfinance refresh.)

See [data_setup.md](data_setup.md) for the fetch script + setup steps.

### Custom ticker subsets

Universe field accepts pseudo-name `"custom"` plus a `customTickers: list[str]`.
Backend writes a per-run instruments file `data/qlib/us_data/instruments/custom_<suffix>.txt`
and uses it as the universe for that run only.

Soft warning thresholds in the FE:
- `<2 tickers` → blocked (red)
- `2–29` → "RankIC will be noisy" (amber)
- `≥30` → "good for stable RankIC" (green)

### Per-run date splits

Six date pickers: train start/end, valid start/end, test start/end.

Defaults shipped with this phase:
- Train: 2008-01-02 → 2015-12-31
- Valid: 2016-01-04 → 2016-12-30
- **Test: 2017-01-03 → 2026-05-07** (extended from 2020-11-04 to use newly-fetched data)

### LLM universe auto-pick

`POST /api/v1/detect-universe` takes the user's objective text and
returns the best-fit universe. FE auto-detects with a 1.2s debounce on
input change when the user has the "auto-pick from objective" checkbox
ticked. Override is always available via the dropdown.

Test results (verified):
- "Mine momentum factors on gold mining stocks" → `commodities` ✅
- "Build NASDAQ tech-heavy momentum factors" → `nasdaq100` ✅

### Per-run config patcher

`_run_mining` writes patched copies of `conf_baseline.yaml` and
`conf_combined_factors.yaml` into `<workspace>/_template_override/` and
sets env var `QA_TEMPLATE_OVERRIDE_DIR`. Workspace loader
([quantaalpha/factors/workspace.py](../quantaalpha/factors/workspace.py))
picks this up and layers it over the project template at runtime.

Patches applied:
- `market` field → chosen universe
- `data_handler_config.instruments` → chosen universe
- `data_handler_config.start_time` / `end_time` → tightest envelope of segments
- `task.dataset.kwargs.segments.{train,valid,test}` → user's dates
- `port_analysis_config.backtest.{start_time,end_time}` → user's test segment
- `benchmark` → auto-mapped: sp500→`^gspc`, nasdaq100→`^ndx`, commodities→`GLD`

## API surface

```
GET  /api/v1/universes              → list available universes + freshness
POST /api/v1/detect-universe        → LLM picks one based on text
POST /api/v1/mining/start           → now accepts: universe, customTickers,
                                                   trainStart, trainEnd,
                                                   validStart, validEnd,
                                                   testStart, testEnd
```

## FE — Advanced panel

Hidden behind a "▸ Advanced" disclosure on ChatInput so the simple-case
user (just type and Send) isn't burdened. When opened, shows:

```
Universe section                Date splits section
  [▼ sp500 (745)        ]         train start  [2008-01-02]
  ☑ auto-pick from objective       train end    [2015-12-31]
  ↪ "..." (LLM rationale)         valid start  [2016-01-04]
  (custom ticker text field        valid end    [2016-12-30]
   appears when "custom"            test start   [2017-01-03]
   selected)                        test end     [2026-05-07]
```

## Acceptance

- All three universes show in `GET /api/v1/universes` with non-null `last_data_mtime`
- "gold" objective → auto-picks commodities; "nasdaq" → nasdaq100
- Custom tickers `AAPL,MSFT,GOOGL` → backend writes `custom_<suffix>.txt`
  with 3 lines (one per ticker)
- A mining run with `universe=commodities` + custom dates produces a
  workspace whose `conf_baseline.yaml` has `market: commodities` and
  the user's segments

## Known caveat

The full pipeline (config-patch → rdagent template injection → mining run)
hasn't been run end-to-end with a live mining session yet. Wiring tests
verify the file-level paths; first real run will be the integration test.
This is captured in [phase_9_smoke_run.md](phase_9_smoke_run.md).

## Future (Phase 12)

- More universes: DJIA, sector ETFs (XLF/XLK/XLE/etc), FX majors, Russell 2000
- `custom_universes.yaml` registry (today the LLM detect prompt is hardcoded)
- Pairs / 2-ticker mining is **NOT** in scope — RankICIR requires ≥30 tickers
  for cross-sectional ranking to be meaningful. See the warning thresholds.
