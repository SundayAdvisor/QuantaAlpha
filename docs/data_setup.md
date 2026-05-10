# Data setup

How to populate / refresh the qlib binary data QuantaAlpha mines on.

> **TL;DR for a fresh setup (or to recover from "all metrics show 0" — see § [Symptom-driven](#symptom-driven-recovery)):**
> ```bash
> # IMPORTANT: --start 2008-01-02 is required so training segments (2008-2015)
> # have actual data. Without this you'll get qlib_res.csv but PortAnaRecord
> # silently fails -> empty backtest_results in the factor library.
> .venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe sp500       --start 2008-01-02 --end $(date +%Y-%m-%d) --rebuild
> .venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe nasdaq100   --start 2008-01-02 --end $(date +%Y-%m-%d) --rebuild
> .venv/Scripts/python.exe scripts/fetch_qlib_data.py --tickers GLD IAU GDX GDXJ SLV USO UNG DBC GSG PDBC --start 2008-01-02 --end $(date +%Y-%m-%d) --rebuild
> ```
> Expect ~15-25 min wall time (yfinance throttling). After it finishes, run
> the [§ Verification step](#verifying-you-have-enough-data) before kicking
> off a mining task — if the verification check fails, your factor library
> entries will show 0s for IC/RankIC/etc. even though mining "succeeds."
>
> See [§ Cookbook](#cookbook) for incremental refreshes, custom universes,
> and recovery scenarios.

## What we have

QuantaAlpha mines factors against qlib-format binary data. The repo ships
**no data** (gitignored) — you have to fetch it yourself. The fetch script
is [scripts/fetch_qlib_data.py](../scripts/fetch_qlib_data.py).

After running the cookbook above, the layout is:

```
data/qlib/us_data/
├── calendars/
│   └── day.txt                  # one YYYY-MM-DD per line, sorted
├── instruments/
│   ├── sp500.txt                # 745 tickers (some delisted post-2020)
│   ├── nasdaq100.txt            # 283 tickers (some delisted)
│   ├── commodities.txt          # 13 ETFs (gold/silver/oil/gas)
│   └── all.txt                  # 8,994 tickers (most stale at 2020-11-10)
└── features/
    └── <ticker_lower>/          # one dir per ticker that has data
        ├── close.day.bin        # float32 LE, prefixed by start_idx
        ├── open.day.bin
        ├── high.day.bin
        ├── low.day.bin
        ├── volume.day.bin
        ├── factor.day.bin       # always 1.0 (adjusted prices)
        └── change.day.bin       # close-to-close return
```

**Calendar coverage** (after the cookbook): 1999-12-31 → today
(~6,600+ trading days).

**⚠️ The calendar can extend further than the actual ticker bins.**
The fetch script writes the calendar from union of all dates it touches,
but each ticker's `.bin` only covers the dates yfinance returned for it.
If you ran an early-version of the fetch script that only pulled forward
from 2020-11-11, your `day.txt` will still LOOK like it spans 2000-today
but `features/<ticker>/close.day.bin` only contains data from 2020-11-11
onward. **This is the silent killer behind "all factor metrics are 0" —
qlib's PortAnaRecord can't run a backtest when the test segment extends
beyond available data.** See [§ Verification](#verifying-you-have-enough-data).

## Universes available out of the box

| Universe | Tickers | Best-fit objective |
|---|---|---|
| `sp500` | 745 (547 fresh post-2020) | US large-cap equities; default, paper-aligned |
| `nasdaq100` | 283 (164 fresh) | Tech-heavy US equities |
| `commodities` | 13 | Gold (GLD/IAU/GDX/GDXJ), silver (SLV/SIVR), platinum (PPLT), oil (USO), gas (UNG), broad (DBC/DBA/GSG/PDBC) |
| `all` | 8,994 | Don't use — too broad, noisy, mostly stale |

A FE drop-down at the home page (Advanced panel) reads `instruments/*.txt`
to populate available universes — so adding a new universe is "create a
`.txt` file + run the fetch script."

## How `fetch_qlib_data.py` works

The script wraps `yfinance` and writes qlib-binary `.bin` files. Modes:

```bash
# Fetch a registered universe (reads instruments/<name>.txt)
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe sp500
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe nasdaq100

# Fetch a custom ticker list
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --tickers SPY QQQ TLT GLD

# Date range overrides (default end = 2026-01-01; default start = inception)
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --tickers AAPL --start 2010-01-01 --end 2026-05-08

# Extend mode — only fetch from existing-calendar-tail forward (cheap refresh)
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --extend

# Full rebuild — overwrite all .bin files
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe sp500 --rebuild
```

Each run:
1. Calls yfinance for each ticker (auto_adjust=True, daily bars)
2. Writes `[start_idx (1 float32)] [N float32 values]` to each `<feature>.day.bin`
3. Merges new dates into `calendars/day.txt` (union + sort)
4. Updates `instruments/<universe>.txt` with each ticker's start/end dates
5. Skips delisted tickers gracefully (logs them, doesn't crash)

## Adding a new universe

Two paths.

### Path A — via instruments file

```bash
# 1. Create the instruments file
echo -e "AAPL\t1990-01-01\t2099-12-31\nMSFT\t1990-01-01\t2099-12-31\n…" \
  > data/qlib/us_data/instruments/tech_megacaps.txt

# 2. Run the fetch
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe tech_megacaps

# 3. Restart QA backend so /api/v1/universes picks it up
```

### Path B — via custom tickers per-run (no instruments file needed)

Use the FE Advanced panel → universe dropdown → "custom" → paste tickers.
QA will write a temp `custom_<suffix>.txt` for that run only.

## Verifying you have enough data

Before kicking off a mining task, sanity-check the bundle's actual ticker
coverage (not just the calendar):

```bash
.venv/Scripts/python.exe -c "
import struct
from pathlib import Path
root = Path('data/qlib/us_data')
cal = root.joinpath('calendars/day.txt').read_text().strip().split()
print(f'Calendar: {len(cal)} days, {cal[0]} -> {cal[-1]}')
for t in ('spy', 'aapl', 'msft', 'jnj', 'ko'):
    p = root / 'features' / t / 'close.day.bin'
    if not p.exists():
        print(f'  {t}: MISSING'); continue
    data = p.read_bytes()
    start_idx = int(struct.unpack('<f', data[:4])[0])
    n = (len(data) // 4) - 1
    print(f'  {t}: {cal[start_idx]} -> {cal[start_idx + n - 1]}  ({n} bars)')
"
```

✅ **Healthy output** — every sample ticker spans at minimum from before
your earliest train date (e.g. `2008-01-02`) through near today:

```
Calendar: 6627 days, 1999-12-31 -> 2026-05-07
  spy:  2008-01-02 -> 2026-05-07  (4623 bars)
  aapl: 2008-01-02 -> 2026-05-07  (4623 bars)
  ...
```

❌ **Broken output** — sample tickers start way after the train segment:

```
Calendar: 6627 days, 1999-12-31 -> 2026-05-07
  spy:  2020-11-11 -> 2026-05-07  (1377 bars)   ← only 5 years of data
  ...
```

If you see the broken pattern, **your training segments will use no data,
PortAnaRecord will silently fail, and the factor library will save zeros.**
Re-run the TL;DR fetch with `--start 2008-01-02 --rebuild` to fix.

## Cookbook — common scenarios

### Fresh machine, never fetched anything

```bash
cd /path/to/QuantaAlpha
# Default sp500/nasdaq100 instruments files ship with the repo
# (they're tab-separated TICKER<TAB>start<TAB>end lines).
# IMPORTANT: explicit --start 2008-01-02 so training segments have data.
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe sp500     --start 2008-01-02 --rebuild  # ~10-15 min
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe nasdaq100 --start 2008-01-02 --rebuild  # ~5 min
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --tickers GLD IAU GDX GDXJ SLV SIVR PPLT USO UNG DBC DBA GSG PDBC --start 2008-01-02 --rebuild  # ~1 min
```

### Symptom-driven recovery

| Symptom | Cause | Fix |
|---|---|---|
| Factor library shows IC=0, RankIC=0, l2.train=0 for every entry | Bundle's per-ticker bins start later than your train segment (e.g. data starts 2020-11-11 but train wants 2008-2015) | Re-fetch with `--start 2008-01-02 --rebuild` |
| `qlib_res.csv` exists in workspace but library still shows 0 | Old version of `library.py` extracted from `experiment.result` only, didn't fall back to disk | Already fixed — `_extract_backtest_results` now reads `qlib_res.csv` directly when `experiment.result is None` |
| `qlib_res.csv` has only IC/RankIC/l2.* but no `1day.*` portfolio metrics | PortAnaRecord ran but couldn't complete the strategy backtest (data range too short or missing) | Refresh data with full historical depth + matching `--end` to your `test_end` |
| `report_normal_1day.pkl` missing → `ret.pkl` missing | PortAnaRecord couldn't write portfolio analysis | Same as above — full historical bundle |
| `instruments/<universe>.txt` lists tickers but their `.bin` files are missing | Tickers were delisted between fetches | Harmless — universe loader skips them |

### Catching data up after a few weeks

```bash
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --extend
```

Walks every existing instruments file, fetches from `(latest_calendar_date + 1)` forward.

### Adding gold-mining stocks (not in any default universe)

```bash
echo -e "NEM\t1990-01-01\t2099-12-31\nGOLD\t1990-01-01\t2099-12-31\nAEM\t1990-01-01\t2099-12-31\nFNV\t1990-01-01\t2099-12-31\nWPM\t1990-01-01\t2099-12-31\nRGLD\t1990-01-01\t2099-12-31\nKGC\t1990-01-01\t2099-12-31" \
  > data/qlib/us_data/instruments/gold_miners.txt
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe gold_miners
```

## Troubleshooting

### "yfinance returned 0 bars for TICKER"

- Most likely the ticker delisted or got acquired. The script logs and
  skips. The `instruments/<universe>.txt` file may still list it from a
  past fetch — that's fine, the universe loader gracefully ignores
  tickers without `<ticker>/close.day.bin`.

### "FileNotFoundError: data/qlib/us_data/calendars/day.txt"

- You haven't fetched anything yet. Run any of the cookbook commands.

### "Too many tickers fetched, my disk is full"

- One ticker × 25 years × all 7 features ≈ 80 KB. So sp500 (~745 tickers)
  ≈ 60 MB. nasdaq100 ≈ 25 MB. Even all-equities (8,994 tickers) ≈ 700 MB.
  Reasonable footprint.

### "I want to re-fetch from scratch"

```bash
rm -rf data/qlib/us_data/features
rm    data/qlib/us_data/calendars/day.txt
.venv/Scripts/python.exe scripts/fetch_qlib_data.py --universe sp500 --rebuild
# (instruments/*.txt are stable; rebuild only touches features/ + calendars/)
```

## Caveats

- **yfinance rate limits**: ~10 requests/sec ceiling. Large fetches (sp500)
  take 5-15 min. If you see HTTP 429, wait an hour.
- **Adjusted prices**: we use `auto_adjust=True`. So `close` is split-and-
  dividend-adjusted. The `factor.day.bin` is always 1.0 because of this —
  qlib's factor mechanism is bypassed.
- **Vwap not computed**: paper's full Alpha158 uses `$vwap` which yfinance
  doesn't provide. QA falls back to the Alpha158(20) feature subset that
  doesn't reference vwap. If you ever need full Alpha158, fetch from a
  source that includes intraday volume-weighted prices.

## Cross-references

- Universe-aware mining (how the FE / backend consume these files): [phase_7_universe_aware_mining.md](phase_7_universe_aware_mining.md)
- The QuantaAlpha integration gotchas memory:
  `~/.claude/projects/.../memory/project_quantaalpha_gotchas.md`
- Paper data conventions: [paper_replication.md](paper_replication.md)
