# US Equity Quickstart (Windows + Claude Code)

Step-by-step for running this fork's mining + backtest pipeline on **US SP500** data, using the local **Claude Code** subscription as the LLM (no per-token API cost).

> Configs in this fork default to US already — just follow the steps. If you need the original CSI 300 setup, see [user_guide.md](user_guide.md).

---

## 0. Prerequisites (one-time)

| Requirement | How |
|---|---|
| **Python 3.10+** (3.12 verified) | https://www.python.org/downloads/ |
| **Git** | https://git-scm.com |
| **Claude Code logged in** | Run `claude login` once. The mining loop drains your Max subscription. |
| **~6 GB disk** | venv ~2 GB + Qlib data ~1 GB + workspace + cache |

---

## 1. Clone the fork

```powershell
git clone https://github.com/SundayAdvisor/QuantaAlpha.git
cd QuantaAlpha
git checkout windows-claude-code
```

## 2. Create venv and install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.0"
pip install -e .
pip install -r requirements.txt
```

> If `pyqlib` install fails on native Windows, try Python 3.10 or 3.11 instead of 3.12.

## 3. Download Qlib's US daily data (~900 MB)

```powershell
.\.venv\Scripts\python.exe -c "from qlib.tests.data import GetData; GetData().qlib_data(name='qlib_data', target_dir='./data/qlib/us_data', interval='1d', region='us', delete_old=False, exists_skip=True)"
```

Coverage: `1999-12-31` to `2020-11-10`. Universes available: `all`, `nasdaq100`, `sp500`.

## 4. Build `daily_pv.h5` for SP500 (with `$return` pre-computed)

The mining loop's CoSTEER coder reads from this. Without `$return` pre-computed, factor.py crashes — the prompt advertises `$return` but Qlib doesn't ship it as a column.

```powershell
.\.venv\Scripts\python.exe -c "
import qlib
from qlib.data import D
import pandas as pd
import os

qlib.init(provider_uri='./data/qlib/us_data', region='us')
instruments = D.instruments(market='sp500')
df = D.features(instruments, ['\$open', '\$close', '\$high', '\$low', '\$volume', '\$factor'],
                start_time='2008-01-01', end_time='2020-11-10', freq='day')
df['\$return'] = df.groupby('instrument')['\$close'].pct_change(fill_method=None).fillna(0)

os.makedirs('git_ignore_folder/factor_implementation_source_data', exist_ok=True)
os.makedirs('git_ignore_folder/factor_implementation_source_data_debug', exist_ok=True)
df.to_hdf('git_ignore_folder/factor_implementation_source_data/daily_pv.h5', key='data', mode='w')

# Debug subset: 5 tickers x 200 days
tickers = list(df.index.get_level_values('instrument').unique()[:5])
sample = df[df.index.get_level_values('instrument').isin(tickers)].groupby('instrument').tail(200)
sample.to_hdf('git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5', key='data', mode='w')
print('Done')
"
```

Expected output: `Done`. Files land at:
- `git_ignore_folder/factor_implementation_source_data/daily_pv.h5` (~150 MB, full)
- `git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5` (~50 KB, debug)

## 5. Configure `.env`

```powershell
Copy-Item configs/.env.claude_code.example .env
```

Open `.env` and **edit these lines for your machine** — replace `<YOUR_PROJECT_ROOT>` with the absolute path to the cloned `QuantaAlpha` directory:

```bash
QLIB_DATA_DIR=<YOUR_PROJECT_ROOT>/data/qlib/us_data
QLIB_PROVIDER_URI=<YOUR_PROJECT_ROOT>/data/qlib/us_data
DATA_RESULTS_DIR=<YOUR_PROJECT_ROOT>/data/results
FACTOR_CoSTEER_PYTHON_BIN=<YOUR_PROJECT_ROOT>/.venv/Scripts/python.exe
FACTOR_CoSTEER_DATA_FOLDER=<YOUR_PROJECT_ROOT>/git_ignore_folder/factor_implementation_source_data
FACTOR_CoSTEER_DATA_FOLDER_DEBUG=<YOUR_PROJECT_ROOT>/git_ignore_folder/factor_implementation_source_data_debug

LLM_PROVIDER=claude_code
CLAUDE_CODE_FALLBACK=none
PYTHONIOENCODING=utf-8
CONDA_DEFAULT_ENV=quantaalpha
```

Use **forward slashes** even on Windows (Qlib is happier).

`CLAUDE_CODE_FALLBACK=none` means "if Claude Code rate limits, fail rather than silently fall back to a paid Anthropic API key." Switch to `anthropic` and add `ANTHROPIC_API_KEY=sk-ant-…` if you want the paid backstop.

## 6. SDK smoke test

Before any real run, verify Claude Code is reachable:

```powershell
.\.venv\Scripts\python.exe scratch\claude_smoke.py
```

Should print 5 PASS lines. If it fails on auth, run `claude login` and retry.

## 7. Run a tiny mining experiment (~3 min wall, ~5 LLM calls)

The shipped `configs/experiment.yaml` is already sized to a smoke run (1 direction, 1 loop, evolution off, 1 factor per hypothesis):

```powershell
.\.venv\Scripts\python.exe launcher.py mine --direction "price-volume factor mining on US equities"
```

Expected: 5 stages complete (`factor_propose → factor_construct → factor_calculate → factor_backtest → feedback`), 3 factors saved to `data/factorlib/all_factors_library.json`.

## 8. Run the independent backtest (~1 min wall)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m quantaalpha.backtest.run_backtest -c configs\backtest.yaml --factor-source custom --factor-json data\factorlib\all_factors_library.json
```

The `-X utf8` flag is **required on Windows** — the script prints `✓` U+2713 which cp1252 can't encode.

Output:

```
[IC Metrics]
  IC: 0.015        ICIR: 0.107
  Rank IC: 0.015   Rank ICIR: 0.110
[Strategy Metrics]
  Ann. Return: +3.92%   Max DD: -20.28%
  Info Ratio: 0.36       Calmar: 0.193
```

Results saved at `data/results/backtest_v2_results/all_factors_library_backtest_metrics.json`.

---

## Scaling beyond the smoke test

Edit `configs/experiment.yaml`:

```yaml
planning:
  enabled: true
  num_directions: 2

execution:
  max_loops: 3

evolution:
  enabled: true
  max_rounds: 3

factor:
  factors_per_hypothesis: 2
```

That's roughly 50–100 LLM calls per run, ~3-4 hours wall. Still well within Max 20× subscription budget.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'charmap' codec can't encode character '✓'` | Use `python -X utf8` flag (or set `PYTHONIOENCODING=utf-8` in shell *before* launching) |
| `index N is out of bounds for axis 0 with size N` from Qlib | Backtest `end_time` is the last calendar day; set it 1 day earlier in `configs/backtest.yaml` |
| `FileNotFoundError: ./daily_pv.h5` during factor_calculate | Step 4 was skipped or `FACTOR_CoSTEER_DATA_FOLDER` env var is wrong |
| Mining loop stuck on `factor_construct` for 10+ minutes | Claude Code session may have lost system-prompt context; check that `LLM_PROVIDER=claude_code` is set and `claude_smoke.py` passes |
| `[WinError 1314] A required privilege is not held` | Symlink permission — already patched in `_windows_patches.py`, but ensure `quantaalpha/__init__.py` actually imports it |

For deep dives on the patches and rationale, see the **`windows-claude-code`** branch's commit messages and `quantaalpha/_windows_patches.py`.

---

## What this fork's `windows-claude-code` branch adds vs upstream

- **Claude Code subscription backend** (`quantaalpha/llm/claude_code_backend.py`) — drains your Max subscription instead of paying per-token to OpenAI/DeepSeek.
- **Dispatcher with fallbacks** (`quantaalpha/llm/dispatch.py`) — Claude Code → Anthropic API → OpenAI-compatible.
- **Windows compatibility patches** (`quantaalpha/_windows_patches.py`) — junctions for symlinks, `select.poll()` shim, `/bin/sh` bypass, `os.symlink` copy fallback, etc.
- **PYTHONPATH separator fix** in `quantaalpha/factors/coder/factor.py` — was hardcoded `:`, now `os.pathsep`.
- **Default configs flipped to US SP500** — `configs/backtest.yaml` and the two `quantaalpha/factors/factor_template/conf_*.yaml` files.

If you want CSI 300, revert those three config files to upstream values and re-do step 4 with the cn dataset.
