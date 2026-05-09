# From Mining to Live Trading — Phase 5, Phase 6, and QuantConnect

This doc explains, in plain language, what happens **after** a QuantaAlpha mining run finishes — how to take the results and use them on real or new data. It also lays out the path to integrating with QuantConnect (QC) for live trading.

If you've read [paper_replication.md](paper_replication.md), this is the next chapter.

---

## Where we are in the bigger picture

```
[Phase 1-4]            [Phase 5]              [Phase 6]              [QC integration]
Mining produces  ──→   Save the model  ──→   Generate scores  ──→   Trade live
factor formulas        + factor list as       on new dates           on QuantConnect
+ trained model        a portable bundle      (CSV output)
(but discards
the model!)
```

Phases 1–4 (mining, evolution, evaluation, baseline) are complete. Phases 5–6 are what bridge "we ran an experiment" to "we have a working trading system." QC integration is the last mile.

---

## The fundamental gap we're filling

QuantaAlpha mining trains a LightGBM **inside every iteration**, uses it to compute IC/RankIC, then **throws it away**. The trajectory pool keeps the *metrics* and *factor formulas*, but not the trained model itself.

The paper's §5.4 zero-shot transfer experiment proves they must save and reload trained models — you can't "directly deploy CSI 300 factors on SPY without re-optimization" without persisting the trained model. But the paper never describes *how*. Phase 5 fills that implementation gap.

Once you have a saved model, you can:
- Apply it to fresh data without re-mining (Phase 6)
- Transfer it to a different market (paper §5.4 style)
- Deploy it on QuantConnect for live trading
- Compare different mining runs by their persisted models
- Roll back to a known-good model after a bad mining iteration

---

## Phase 5 — Save the chef and the recipes

**Plain-language analogy.** Think of QuantaAlpha mining as a factory that produces a recipe book and a chef:
- The **recipe book** is the list of factor formulas (e.g. *"compute 20-day correlation between price and volume, then take the cross-sectional rank"*)
- The **chef** is the trained LightGBM model — the thing that takes those factor values and produces a single "buy this stock" score

Mining throws both away when it finishes. Phase 5 saves them as a folder you can copy/paste anywhere.

**Script**: [`extract_production_model.py`](../extract_production_model.py)

### What it does, step by step

1. **Find the latest mining workspace.** Auto-detects the most recent `data/results/workspace_exp_*` folder, or you can point it at a specific one with `--workspace`.

2. **Locate the final factor pool.** Finds `combined_factors_df.parquet` in that workspace — this is the curated list of factor values that survived the admission filter (the "best recipes" after the |corr|<0.7 + 50% cap rule).

3. **Re-train one final LightGBM** on the combined train+valid window (more data → better model). The mining loop trained smaller models inside each iteration, but those weren't kept. This step trains a fresh LightGBM on **everything we know** — train AND valid combined — using the same hyperparameters from `conf_combined_factors.yaml`. This is the "production" model.

4. **Test on the held-out test window** to confirm IC/RankIC didn't collapse. Sanity check that the production model performs at least as well as the in-iteration models did.

5. **Save the bundle** to `data/results/production_models/spy_production_<timestamp>/`:

```
spy_production_20260507_220000/
  ├── model.lgbm                  ← the trained chef (LightGBM binary, joblib-pickled)
  ├── factor_expressions.yaml     ← the recipe book (readable text)
  ├── extraction_conf.yaml        ← qlib config used to train, kept for reproducibility
  └── metadata.json               ← train dates, market, hyperparameters, held-out IC
```

This bundle is **portable**. You can zip it, version-control it, share it, or upload it to QC.

### Usage

```powershell
# Default — auto-find latest mining workspace
.venv\Scripts\python.exe extract_production_model.py

# Point at a specific workspace
.venv\Scripts\python.exe extract_production_model.py --workspace data/results/workspace_exp_20260507_211331

# Smoke-test mode — no mined factors, just the 20 Alpha158 baseline (~80 seconds)
.venv\Scripts\python.exe extract_production_model.py --baseline
```

### Pass criteria

- Exit code 0
- `metadata.json` shows `test_ic` not None and not collapsed (ideally ≥ baseline anchor's 0.0032)
- `model.lgbm` exists and joblib can re-load it
- `factor_expressions.yaml` lists the factors that were in the final pool

---

## Phase 6 — Use the chef and recipes on new data

**Plain-language**: feed the bundle some dates, get back a CSV of "for each stock, on each day, here's how good our model thinks it is."

**Script**: [`predict_with_production_model.py`](../predict_with_production_model.py)

### What it does, step by step

You give the script:
- The bundle folder from Phase 5 (`--bundle` argument)
- A date range (`--start`, `--end`)
- Optional: just the top-N picks per day (`--topk`)

It does this:

1. **Load the trained model** from `model.lgbm` via joblib
2. **Load the qlib config** from `extraction_conf.yaml` (knows which market, which features, which preprocessing)
3. **Modify the config's `test` segment** to be the date range you asked about
4. **Build the qlib dataset** for that range — qlib computes the 20 Alpha158 features fresh, joins with the parquet of mined factors, applies CSRankNorm preprocessing
5. **Run `model.predict(dataset)`** → score per (date, stock)
6. **Output a CSV** with columns `datetime, instrument, score`, sorted by date then score

If `--topk N` is set, only the top-N stocks per day are written (paper-style universe selection).

### Usage

```powershell
# Predict scores for every SPY stock on every day in November 2020
.venv\Scripts\python.exe predict_with_production_model.py \
    --bundle data/results/production_models/spy_production_20260507_220000 \
    --start 2020-11-01 --end 2020-11-04 \
    --output predictions.csv

# Top-50 picks per day (paper-style)
.venv\Scripts\python.exe predict_with_production_model.py \
    --bundle data/results/production_models/spy_production_20260507_220000 \
    --start 2020-11-01 --end 2020-11-04 \
    --topk 50 \
    --output topk_picks.csv
```

### Output format

```
datetime,instrument,score
2020-11-02,A,0.0142
2020-11-02,AAPL,-0.0089
2020-11-02,MSFT,0.0271
...
```

### Limitation: prediction window must overlap the parquet

The Phase 5 bundle's parquet covers specific dates (the dates QuantaAlpha mined on). Phase 6 by default predicts on dates **within that parquet's coverage**. If you ask for dates beyond it, the parquet won't have factor values and predictions will be NaN.

For predictions on truly new dates (e.g. November 2024 when the parquet only covers through 2020-11-04), you'd need to **recompute the factor values fresh from the formulas in `factor_expressions.yaml`** for those new dates. That's a small additional script — see "Future work" at the bottom.

---

## Can I use a different model? (Yes — here's how)

Phase 5 and Phase 6 are model-agnostic. They speak qlib's model interface, and **any model that fits the `model.fit(dataset)` / `model.predict(dataset)` contract works**.

### Models qlib supports out-of-the-box

| Model | Class path | When to use |
|---|---|---|
| **LightGBM** (current) | `qlib.contrib.model.gbdt.LGBModel` | Paper's choice. Fast, robust, the right default. |
| **XGBoost** | `qlib.contrib.model.xgboost.XGBModel` | Similar to LightGBM, slightly different splits. Useful as A/B comparison. |
| **CatBoost** | `qlib.contrib.model.catboost_model.CatBoostModel` | Better for noisy data; slower. Try if LightGBM overfits. |
| **MLP** | `qlib.contrib.model.pytorch_nn.DNNModelPytorch` | Pure feedforward neural net. Captures non-linearities GBT misses. |
| **GRU / LSTM** | `qlib.contrib.model.pytorch_gru.GRU`, `pytorch_lstm.LSTM` | Sequence models — use raw price history (Alpha360-style features), not factor expressions. |
| **Transformer** | `qlib.contrib.model.pytorch_transformer.TransformerModel` | Heavy. Best for long-range dependencies. Slow to train. |
| **TRA** | `qlib.contrib.model.pytorch_tra.TRAModel` | Best DL baseline in paper Table 1 (IC=0.0421 on CSI 300, no mined factors). |
| **DoubleEnsemble** | `qlib.contrib.model.double_ensemble.DEnsembleModel` | Ensemble of GBT models. Can squeeze a bit more out of weak signals. |

### How to swap

1. Edit `conf_combined_factors.yaml` (or your bundle's `extraction_conf.yaml`):
```yaml
task:
    model:
        class: qlib.contrib.model.xgboost.XGBModel    # was: gbdt.LGBModel
        kwargs:
            # XGBoost-specific hyperparams here
            ...
```

2. Re-run Phase 5: `extract_production_model.py` will pick up the new model class and train it. The bundle still saves as `model.lgbm` (file name is just legacy — the file actually contains whatever model was trained).

3. Phase 6 loads it back via `joblib.load(...)` — works identically because joblib can serialize any Python object.

### Important caveat

You can't "use a different model in Phase 6 without re-training in Phase 5." The model has to be trained on the specific feature set (the 20 baseline + N mined factors). If you want a Transformer instead of LightGBM, you have to:
1. Change the config in Phase 5
2. Re-run Phase 5 (which retrains)
3. Phase 6 then uses the new model

You can have **multiple bundles** side by side — train an LGBM bundle and an XGBoost bundle from the same mining run, then compare their Phase 6 outputs to see which model does better on held-out dates.

### Recommendation for your first run

Stick with LightGBM. It's the paper's choice, fast (matters because each Phase 5 retrain is a couple minutes), and well-tested on this kind of factor-engineered data. Once you have a baseline working end-to-end through QC, *then* experiment with model class as an optimization knob.

---

## QuantConnect integration paths

Once you have a Phase 5 bundle, getting it to drive trades on QuantConnect is the last step. Three options, easiest to hardest. **You don't need to decide now** — they all use the same Phase 5 bundle as input.

### Path A — Daily batch upload (recommended start)

```
You (laptop)                                      QuantConnect cloud
─────────────                                     ──────────────────
                                                                
Each evening:                                                   
  Phase 6 → predictions.csv                                     
                                                                
                Upload CSV via Object Store API ─────────→ Object Store
                                                                
                                                         At market open:
                                                         QC algo:
                                                         1. Read CSV
                                                         2. Pick top-50
                                                         3. Submit orders
```

- **You** run Phase 6 daily (or schedule it as a cron job) → produces a CSV of next-day's scores
- **QC algo** is small and simple: at the morning's open, read the CSV, pick top-50, submit orders, drop bottom-5
- **Pro**: trivially simple QC code (~50 lines), all complexity stays on your laptop where you can debug it
- **Con**: you're in the loop daily; if your laptop is down, no trades. Not fully autonomous.
- **What you'd build**: a `predict_for_quantconnect.py` wrapper around Phase 6 that outputs in QC's expected format (`date, symbol, weight`)

### Path B — In-broker inference (what real funds do)

```
QuantConnect cloud
──────────────────

Each market open:
  QC algo:
    1. Pull recent OHLCV from QC data API
    2. Compute factor values from
       factor_expressions.yaml  ← needs a portable evaluator
    3. Stack features → matrix
    4. model.lgbm.predict(matrix) → scores
    5. Pick top-50, submit orders
```

- **Upload** `model.lgbm` and `factor_expressions.yaml` to QC's Object Store once
- **QC algo** loads them at startup and uses them in-broker
- **Pro**: fully autonomous; QC handles everything end-to-end
- **Con**: factor formulas use qlib syntax (`TS_CORR($close, $volume, 20)`) — QC's indicator system is different. You either:
  - **Translate each formula** to QC's `Indicator` API (one-time work, ~50–150 expressions)
  - **Port the qlib expression evaluator** so it runs on QC's pandas DataFrames (more general, more work upfront, but reusable)
- The model itself loads cleanly — LightGBM is just a binary file QC can `joblib.load`

### Path C — Online inference via API

```
QuantConnect cloud                         Your VPS
──────────────────                         ────────

Each market open:                          Flask/FastAPI service
  QC algo:                                 with model.lgbm loaded
    1. Pull recent OHLCV                   in memory:
    2. POST features ───→ /predict ───→
                                           Compute predictions
                                           Return scores
    3. Receive scores ←──────────────────  
    4. Top-50, submit orders               
```

- **Host** your model behind a small Flask/FastAPI service on a tiny VPS
- **QC algo** POSTs daily features to the service and gets scores back
- **Pro**: model stays on your infrastructure, easy to update without re-deploying QC code
- **Con**: another moving piece (uptime, auth, latency); risk if your VPS is down at market open

### My recommended sequence

1. **Path A first.** Get the daily-CSV workflow working. Verify the model's predictions actually translate to profitable trades on QC paper-trading. Cheap, fast feedback loop.
2. **Then Path B**, once you trust the model. The in-broker version saves you operational overhead and removes the laptop-as-single-point-of-failure.
3. **Path C** is rarely worth it for personal trading unless you have multiple QC algos sharing one model.

You can defer this decision. Phase 5/6 produce the same bundle regardless — the choice is just about how QC consumes it.

---

## What's NOT built yet (current gaps)

As of 2026-05-09, this is the honest state of the pipeline:

- **No factor-trained bundle yet.** Two bundles exist (`smoke_test_baseline`, `smoke_test_baseline_v2`)
  but both have `num_factors_in_metadata: 0` — they were trained on the 20 baseline features only.
  `test_rank_ic ≈ 0.005` (noise level), as expected. To produce a bundle that meaningfully reflects
  QA's mined alpha, run `extract_production_model.py` against a workspace where a real mining run
  has produced `combined_factors_df.parquet` files.
- **No QC-side consumer.** `qc_multi_strategy_architecture.md` describes a `QAAlphaModel` class for
  QC's Alpha Framework — that class does not exist. Bundles land in `data/results/production_models/`
  and have nowhere to go. A QC strategy that loads a Phase 5 bundle and calls `model.predict(features)`
  is on the roadmap (see `repos/QuantaQC/docs/roadmap.md`) but not written.
- **No "Production Models" tab in the QA frontend.** Bundles aren't listed/inspectable through the UI
  — you have to look on disk. A FE tab listing bundles + showing each one's metadata + a download button
  would close the loop visually. Tracked.
- **No fresh-data inference path.** Phase 6 predicts within the parquet's date range. To predict on
  *tomorrow's* data, we'd need `compute_factors_fresh.py` that takes `factor_expressions.yaml` + new
  OHLCV and computes factor values without re-running mining. This is what feeds the in-broker
  deployment (Path B above).
- **No bundle versioning / registry.** Bundles are file-system snapshots. Good enough for two users;
  if multi-user, swap to MLflow or similar later.
- **No retraining cadence.** Alpha decays. Plan: re-mine + re-extract every N weeks, A/B old-vs-new,
  retire stale bundles. Not automated.

## Future work (longer-horizon, post-MVP)

- **Multi-model bundles.** Train LGBM + XGBoost + CatBoost on the same factor pool, ensemble their predictions. Cheap diversity gain.
- **Cross-market transfer (paper §5.4 style).** Train a bundle on one market, apply to another. Requires getting CSI 300 data, but the bundle format already supports it — just point Phase 6 at a CSI bundle while loading SPY data.
- **Live retraining schedule.** The model degrades over time as markets change (alpha decay). Add a re-mining cadence — e.g. every quarter, run a fresh mining loop, produce a new bundle, A/B against the old one.

---

## Files this doc references

```
extract_production_model.py            (Phase 5 — written)
predict_with_production_model.py       (Phase 6 — written)
data/results/production_models/        (where bundles land)
docs/paper_replication.md              (the previous chapter — config alignment)
docs/phase_5_6_and_quantconnect.md     (this file)
```
