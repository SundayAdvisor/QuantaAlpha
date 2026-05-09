"""
Phase 6: predict scores using a saved production model.

Why this exists:
    After Phase 5 (extract_production_model.py) saves a bundle, you need a way
    to apply that bundle to dates and generate trading signals. This is that
    way. It loads the trained model + the qlib config, builds a dataset for the
    requested date range, runs predictions, and writes a CSV.

What it does:
    1. Load model.lgbm + extraction_conf.yaml from the bundle.
    2. Modify the conf's `test` segment to be the requested [start, end] range.
    3. Build a qlib dataset (auto-computes the 20 baseline + joins parquet
       factors + applies CSRankNorm — same pipeline as during training).
    4. Run model.predict on the test segment.
    5. Save to CSV: datetime, instrument, score (sorted by date then score).
    6. Optionally output only top-N picks per day.

Limitations:
    Predictions only work for dates the parquet covers (the dates QuantaAlpha
    mined on). For truly new dates, you need a separate "compute factors fresh"
    step — see docs/phase_5_6_and_quantconnect.md "Future work".

Usage:
    .venv\\Scripts\\python.exe predict_with_production_model.py \\
        --bundle data/results/production_models/spy_production_20260507_220000 \\
        --start 2020-11-01 --end 2020-11-04 \\
        --output predictions.csv

    .venv\\Scripts\\python.exe predict_with_production_model.py \\
        --bundle data/results/production_models/spy_production_20260507_220000 \\
        --start 2020-11-01 --end 2020-11-04 \\
        --topk 50 \\
        --output topk_picks.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent


def load_bundle(bundle_dir: Path) -> dict:
    """Load and validate a Phase 5 bundle. Returns dict of paths + metadata."""
    if not bundle_dir.exists():
        raise FileNotFoundError(f"Bundle dir not found: {bundle_dir}")

    model_path = bundle_dir / "model.lgbm"
    conf_path = bundle_dir / "extraction_conf.yaml"
    factors_path = bundle_dir / "factor_expressions.yaml"
    metadata_path = bundle_dir / "metadata.json"

    for p in (model_path, conf_path, metadata_path):
        if not p.exists():
            raise FileNotFoundError(f"Bundle is incomplete — missing {p.name}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    factors = (
        yaml.safe_load(factors_path.read_text(encoding="utf-8")) or {}
        if factors_path.exists()
        else {}
    )

    return {
        "bundle_dir": bundle_dir,
        "model_path": model_path,
        "conf_path": conf_path,
        "factors_path": factors_path,
        "metadata": metadata,
        "factors": factors,
    }


def patch_test_segment(conf_path: Path, start: str, end: str, output_dir: Path) -> Path:
    """
    Make a copy of the bundle's qlib conf with the test segment rewritten to
    the requested date range. Returns the path to the patched conf.
    """
    cfg = yaml.safe_load(conf_path.read_text(encoding="utf-8"))

    # Replace the test segment with the prediction window.
    # Train/valid stay as-is (qlib still loads them but we won't use them).
    cfg["task"]["dataset"]["kwargs"]["segments"]["test"] = [start, end]

    # Also widen the data_handler end_time if needed so qlib loads the requested range
    handler_end = cfg["data_handler_config"].get("end_time")
    if handler_end and end > str(handler_end):
        cfg["data_handler_config"]["end_time"] = end

    patched = output_dir / "predict_conf.yaml"
    patched.write_text(yaml.safe_dump(cfg, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return patched


def predict(bundle: dict, start: str, end: str, topk: Optional[int]) -> "pd.DataFrame":
    """Run predictions and return a DataFrame with (datetime, instrument, score)."""
    import qlib
    from qlib.utils import init_instance_by_config
    import joblib
    import pandas as pd

    print(f"[predict] loading model from {bundle['model_path']}")
    model = joblib.load(bundle["model_path"])

    # Materialize a patched conf to a temp location next to the bundle
    tmp_dir = bundle["bundle_dir"] / "_predict_tmp"
    tmp_dir.mkdir(exist_ok=True)
    patched_conf = patch_test_segment(bundle["conf_path"], start, end, tmp_dir)

    cfg = yaml.safe_load(patched_conf.read_text(encoding="utf-8"))
    print(f"[predict] qlib init (provider_uri={cfg['qlib_init']['provider_uri']})")
    qlib.init(**cfg["qlib_init"])

    print(f"[predict] building dataset for {start} → {end}")
    t0 = time.time()
    dataset = init_instance_by_config(cfg["task"]["dataset"])
    print(f"[predict]   dataset ready in {time.time()-t0:.1f}s")

    print("[predict] running model.predict on test segment...")
    t0 = time.time()
    preds = model.predict(dataset, segment="test")
    print(f"[predict]   predictions ready in {time.time()-t0:.1f}s ({len(preds)} rows)")

    # qlib returns a Series indexed by (datetime, instrument); flatten to a DataFrame
    df = preds.reset_index()
    df.columns = ["datetime", "instrument", "score"]
    df = df.sort_values(["datetime", "score"], ascending=[True, False]).reset_index(drop=True)

    if topk is not None:
        # Keep only the top-N stocks per day
        before = len(df)
        df = df.groupby("datetime", group_keys=False).head(topk).reset_index(drop=True)
        print(f"[predict] top-{topk} filter: {before} → {len(df)} rows")

    return df


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=str, required=True,
                        help="Path to a Phase 5 bundle directory.")
    parser.add_argument("--start", type=str, required=True,
                        help="First prediction date (YYYY-MM-DD).")
    parser.add_argument("--end", type=str, required=True,
                        help="Last prediction date (YYYY-MM-DD, inclusive).")
    parser.add_argument("--output", type=str, default="predictions.csv",
                        help="Output CSV path. Defaults to predictions.csv in cwd.")
    parser.add_argument("--topk", type=int, default=None,
                        help="If set, keep only the top-N stocks per day (paper-style universe). "
                             "Omit to get full per-day, per-stock scores.")
    args = parser.parse_args()

    try:
        bundle = load_bundle(Path(args.bundle).resolve())
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    print(f"[predict] bundle: {bundle['bundle_dir']}")
    print(f"[predict]   model class:   {bundle['metadata'].get('model_class')}")
    print(f"[predict]   trained range: {bundle['metadata'].get('train_segments', {}).get('train')}")
    print(f"[predict]   held-out IC:   {bundle['metadata'].get('test_ic')}")
    print(f"[predict]   # factors:     {bundle['metadata'].get('num_factors_in_metadata')}")

    df = predict(bundle, args.start, args.end, args.topk)

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    print()
    print("=" * 60)
    print("PREDICTIONS WRITTEN")
    print("=" * 60)
    print(f"  Output:        {out_path}")
    print(f"  Rows:          {len(df)}")
    print(f"  Date range:    {df['datetime'].min()} → {df['datetime'].max()}")
    print(f"  Score range:   [{df['score'].min():.4f}, {df['score'].max():.4f}]")
    print(f"  Score mean:    {df['score'].mean():.6f}")
    if args.topk:
        print(f"  Top-K filter:  {args.topk} per day")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
