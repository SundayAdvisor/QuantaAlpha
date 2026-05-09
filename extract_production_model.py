"""
Phase 5: train and persist a production model from a completed mining run.

Why this exists:
    Each iteration of QuantaAlpha trains a LightGBM internally and discards it
    after computing metrics. The paper's §5.4 zero-shot transfer experiment
    requires a *kept* trained model — they don't describe the save step
    explicitly, but it's necessary for the methodology. This script fills that
    implementation gap.

What it does:
    1. Locate the most recent (or specified) mining workspace.
    2. Find the final iteration's combined_factors_df.parquet (the
       admission-filtered, cumulative factor pool).
    3. Build a qlib config that uses that parquet alongside the 20 Alpha158
       baseline features.
    4. Train a fresh LightGBM on train+valid (combined for production) using
       the same hyperparameters as conf_combined_factors.yaml.
    5. Save: model.lgbm + factor_expressions.yaml + metadata.json.

Usage:
    .venv\\Scripts\\python.exe extract_production_model.py
    .venv\\Scripts\\python.exe extract_production_model.py --workspace data/results/workspace_exp_20260507_211331
    .venv\\Scripts\\python.exe extract_production_model.py --baseline   # use baseline 20 features only (smoke test)

The bundle produced is what predict_with_production_model.py loads.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = REPO_ROOT / "data" / "results"
TEMPLATE_COMBINED = REPO_ROOT / "quantaalpha" / "factors" / "factor_template" / "conf_combined_factors.yaml"
TEMPLATE_BASELINE = REPO_ROOT / "quantaalpha" / "factors" / "factor_template" / "conf_baseline.yaml"
PRODUCTION_DIR = REPO_ROOT / "data" / "results" / "production_models"


def find_latest_workspace() -> Optional[Path]:
    """Return the most recently modified workspace_exp_* directory."""
    if not RESULTS_DIR.exists():
        return None
    candidates = sorted(
        (p for p in RESULTS_DIR.iterdir() if p.is_dir() and p.name.startswith("workspace_exp_")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def find_final_parquet(workspace: Path) -> Optional[Path]:
    """Find the most recently modified combined_factors_df.parquet in a workspace."""
    parquets = sorted(
        workspace.glob("*/combined_factors_df.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return parquets[0] if parquets else None


def build_extraction_config(
    template: Path,
    parquet_path: Optional[Path],
    output_dir: Path,
) -> Path:
    """
    Materialize a qlib config in `output_dir`. Combined-factors mode rewrites
    the StaticDataLoader to point at the absolute parquet path. Baseline mode
    leaves the template unchanged.
    """
    cfg = yaml.safe_load(template.read_text(encoding="utf-8"))

    # For production, train on train+valid combined (more data → better model).
    # Keep test as a small sanity-check window.
    seg = cfg["task"]["dataset"]["kwargs"]["segments"]
    train_start = seg["train"][0]
    valid_end = seg["valid"][1]
    cfg["task"]["dataset"]["kwargs"]["segments"] = {
        "train": [train_start, valid_end],          # combine train + valid
        "valid": seg["valid"],                       # keep small valid for early stopping
        "test": seg["test"],                         # held-out for sanity metrics
    }

    if parquet_path is not None:
        # Rewrite the StaticDataLoader path to the absolute final parquet
        for loader in cfg["data_handler_config"]["data_loader"]["kwargs"]["dataloader_l"]:
            if loader.get("class") == "qlib.data.dataset.loader.StaticDataLoader":
                loader["kwargs"]["config"] = str(parquet_path.absolute())

    out_path = output_dir / "extraction_conf.yaml"
    out_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    return out_path


def collect_factor_expressions(workspace: Path) -> list[dict]:
    """
    Pull factor name + expression pairs from the trajectory pool of the run.
    Falls back to empty list if the pool isn't found.
    """
    # Look for the run's trajectory_pool.json
    log_dir = REPO_ROOT / "log"
    if not log_dir.exists():
        return []

    candidates = sorted(
        log_dir.glob("*/trajectory_pool.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return []

    pool = json.loads(candidates[0].read_text(encoding="utf-8"))
    out = []
    for traj in (pool.get("trajectories") or {}).values():
        rank_ic = (traj.get("backtest_metrics") or {}).get("RankIC")
        for f in traj.get("factors", []):
            out.append({
                "name": f.get("name"),
                "expression": f.get("expression"),
                "description": f.get("description", "")[:300],
                "trajectory_id": traj.get("trajectory_id"),
                "trajectory_rank_ic": rank_ic,
            })
    return out


def train_and_save(conf_path: Path, output_dir: Path, factor_metadata: list[dict]) -> dict:
    """Run qlib's task_train programmatically, extract the trained model, save it."""
    import qlib
    from qlib.utils import init_instance_by_config
    import joblib

    cfg = yaml.safe_load(conf_path.read_text(encoding="utf-8"))
    qlib.init(**cfg["qlib_init"])

    print("[extract] building dataset (this loads features + labels)...")
    t0 = time.time()
    dataset = init_instance_by_config(cfg["task"]["dataset"])
    print(f"[extract]   dataset ready in {time.time()-t0:.1f}s")

    print("[extract] training LightGBM on combined train+valid...")
    t0 = time.time()
    model = init_instance_by_config(cfg["task"]["model"])
    model.fit(dataset)
    print(f"[extract]   model trained in {time.time()-t0:.1f}s")

    # Sanity-check predictions on the small held-out test
    print("[extract] computing held-out test metrics...")
    try:
        preds = model.predict(dataset, segment="test")
        labels = dataset.prepare("test", col_set="label", data_key="raw")
        from qlib.contrib.eva.alpha import calc_ic  # type: ignore
        ic_series, ric_series = calc_ic(preds, labels.iloc[:, 0])
        test_ic = float(ic_series.mean())
        test_ric = float(ric_series.mean())
    except Exception as e:
        print(f"[extract]   (skipped held-out IC: {e})")
        test_ic = None
        test_ric = None

    # Save model
    model_path = output_dir / "model.lgbm"
    joblib.dump(model, model_path)

    # Save factor metadata
    factors_yaml = output_dir / "factor_expressions.yaml"
    factors_yaml.write_text(
        yaml.safe_dump({"factors": factor_metadata}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    # Save run metadata
    metadata = {
        "saved_at": datetime.now().isoformat(),
        "qlib_provider_uri": cfg["qlib_init"]["provider_uri"],
        "market": cfg["market"],
        "benchmark": cfg["benchmark"],
        "train_segments": cfg["task"]["dataset"]["kwargs"]["segments"],
        "model_class": cfg["task"]["model"]["class"],
        "model_kwargs": cfg["task"]["model"]["kwargs"],
        "test_ic": test_ic,
        "test_rank_ic": test_ric,
        "num_factors_in_metadata": len(factor_metadata),
        "extraction_conf": str(conf_path),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=str, default=None,
                        help="Path to a completed workspace_exp_* directory. "
                             "If omitted, the most recent one is used.")
    parser.add_argument("--baseline", action="store_true",
                        help="Skip mined factors; produce a baseline-only model "
                             "from the 20 Alpha158 features (smoke test).")
    parser.add_argument("--output-name", type=str, default=None,
                        help="Sub-directory name under data/results/production_models/. "
                             "Defaults to a timestamp.")
    args = parser.parse_args()

    PRODUCTION_DIR.mkdir(parents=True, exist_ok=True)
    out_name = args.output_name or f"spy_production_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = PRODUCTION_DIR / out_name
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[extract] output dir: {output_dir}")

    if args.baseline:
        print("[extract] BASELINE mode: 20 Alpha158 features only, no mined factors")
        conf_path = build_extraction_config(TEMPLATE_BASELINE, parquet_path=None, output_dir=output_dir)
        factor_metadata: list[dict] = []
    else:
        if args.workspace:
            workspace = Path(args.workspace)
        else:
            workspace = find_latest_workspace()
            if workspace is None:
                print("[ERROR] no workspace_exp_* directory found in data/results/", file=sys.stderr)
                print("[ERROR] either run a mining experiment first or use --baseline", file=sys.stderr)
                return 2

        print(f"[extract] using workspace: {workspace}")
        parquet = find_final_parquet(workspace)
        if parquet is None:
            print(f"[ERROR] no combined_factors_df.parquet found in {workspace}", file=sys.stderr)
            print("[ERROR] mining run may not be complete; use --baseline as fallback", file=sys.stderr)
            return 3

        print(f"[extract] using factor parquet: {parquet}")
        conf_path = build_extraction_config(TEMPLATE_COMBINED, parquet, output_dir)
        factor_metadata = collect_factor_expressions(workspace)
        print(f"[extract] collected {len(factor_metadata)} factor expressions from trajectory pool")

    metadata = train_and_save(conf_path, output_dir, factor_metadata)

    print()
    print("=" * 60)
    print("PRODUCTION MODEL SAVED")
    print("=" * 60)
    print(f"  Bundle:        {output_dir}")
    print(f"  Held-out IC:   {metadata.get('test_ic')}")
    print(f"  Held-out RIC:  {metadata.get('test_rank_ic')}")
    print(f"  Train range:   {metadata['train_segments']['train']}")
    print(f"  # factors:     {metadata['num_factors_in_metadata']}")
    print("=" * 60)
    print()
    print("Next: predict_with_production_model.py --bundle", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
