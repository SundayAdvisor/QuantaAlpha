#!/usr/bin/env python3
"""
Backfill missing backtest_metrics in trajectory_pool.json files.

The bug: when upstream rdagent's QlibFBWorkspace.execute() returns None
(because ret.pkl wasn't produced), every trajectory's backtest_metrics
ends up `{}`. The history page then shows "—" for best_rank_icir / best_ir
even though qlib_res.csv with valid IC/ICIR/RankIC/RankICIR/l2.* was
written to disk.

This tool walks each run dir, reads the pickled `runner result/*.pkl`
files to recover the experiment_workspace path, reads qlib_res.csv from
those workspaces, and patches the matching trajectory's
backtest_metrics in trajectory_pool.json.

Usage:
    .venv/Scripts/python.exe scripts/backfill_trajectory_metrics.py
    .venv/Scripts/python.exe scripts/backfill_trajectory_metrics.py --run 2026-05-10_09-37-47-612370
    .venv/Scripts/python.exe scripts/backfill_trajectory_metrics.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_ROOT = REPO_ROOT / "log"

# Map qlib_res.csv index names → trajectory backtest_metrics keys
INDEX_MAPPING = {
    "IC": ["IC", "ic"],
    "ICIR": ["ICIR", "icir"],
    "RankIC": ["RankIC", "Rank IC", "rank_ic"],
    "RankICIR": ["RankICIR", "Rank ICIR", "rank_icir"],
    "annualized_return": [
        "1day.excess_return_with_cost.annualized_return",
        "1day.excess_return_without_cost.annualized_return",
        "annualized_return",
    ],
    "information_ratio": [
        "1day.excess_return_with_cost.information_ratio",
        "1day.excess_return_without_cost.information_ratio",
        "information_ratio",
    ],
    "max_drawdown": [
        "1day.excess_return_with_cost.max_drawdown",
        "1day.excess_return_without_cost.max_drawdown",
        "max_drawdown",
    ],
}


def extract_metrics_from_csv(csv_path: Path) -> dict[str, Optional[float]]:
    """Read qlib_res.csv and project into the trajectory metric keys."""
    metrics: dict[str, Optional[float]] = {k: None for k in INDEX_MAPPING}
    df = pd.read_csv(csv_path, index_col=0)
    if df.empty or df.shape[1] < 1:
        return metrics
    series = df.iloc[:, 0]
    for target, names in INDEX_MAPPING.items():
        for name in names:
            if name in series.index:
                val = series[name]
                if pd.notna(val):
                    metrics[target] = float(val)
                    break
    return metrics


def find_phase_round_dirs(run_dir: Path) -> list[tuple[Path, str, int, int]]:
    """Find phase_round_dir entries: (path, phase, round_idx, direction_id)."""
    out: list[tuple[Path, str, int, int]] = []
    pat = re.compile(r"^(original|mutation|crossover)_(\d{2})_(\d{2})$")
    for p in run_dir.iterdir():
        if not p.is_dir():
            continue
        m = pat.match(p.name)
        if not m:
            continue
        phase, rnd, dir_id = m.group(1), int(m.group(2)), int(m.group(3))
        out.append((p, phase, rnd, dir_id))
    return out


def get_workspace_path_from_pickle(phase_round_dir: Path) -> Optional[Path]:
    """Walk runner result/ pickles to extract experiment_workspace.workspace_path."""
    rr = phase_round_dir / "ef" / "runner result"
    if not rr.exists():
        return None
    for pkl_file in sorted(rr.rglob("*.pkl")):
        try:
            with open(pkl_file, "rb") as f:
                exp = pickle.load(f)
            ws = getattr(exp, "experiment_workspace", None)
            ws_path = getattr(ws, "workspace_path", None) if ws is not None else None
            if ws_path is not None:
                return Path(str(ws_path))
        except Exception:
            continue
    return None


def patch_run(run_dir: Path, dry_run: bool) -> dict:
    """Patch one run dir. Returns counts."""
    pool_path = run_dir / "trajectory_pool.json"
    if not pool_path.exists():
        return {"skipped": "no trajectory_pool.json", "patched": 0, "total": 0}

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    trajs = pool.get("trajectories") or {}

    # Build a map: (phase, round_idx, direction_id) → trajectory_id
    by_position: dict[tuple[str, int, int], str] = {}
    for tid, t in trajs.items():
        key = (t.get("phase", ""), t.get("round_idx", -1), t.get("direction_id", -1))
        by_position[key] = tid

    patched = 0
    total_empty = sum(1 for t in trajs.values() if not t.get("backtest_metrics"))

    for prdir, phase, rnd, dir_id in find_phase_round_dirs(run_dir):
        tid = by_position.get((phase, rnd, dir_id))
        if tid is None:
            continue
        traj = trajs[tid]
        if traj.get("backtest_metrics"):
            continue  # already populated
        ws_path = get_workspace_path_from_pickle(prdir)
        if ws_path is None:
            continue
        csv_path = ws_path / "qlib_res.csv"
        if not csv_path.exists():
            continue
        try:
            metrics = extract_metrics_from_csv(csv_path)
        except Exception as e:
            print(f"  [{tid[:8]}] failed to read csv: {e}")
            continue
        if not any(v is not None for v in metrics.values()):
            continue
        patched += 1
        non_null = {k: v for k, v in metrics.items() if v is not None}
        print(f"  [{phase}_{rnd:02d}_{dir_id:02d}] {tid[:8]}: {non_null}")
        if not dry_run:
            traj["backtest_metrics"] = metrics

    if patched and not dry_run:
        pool["saved_at"] = datetime.now().isoformat()
        pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"patched": patched, "total": len(trajs), "empty_before": total_empty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", default=str(DEFAULT_LOG_ROOT))
    parser.add_argument("--run", default=None, help="Patch only this run_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log_root = Path(args.log_root)
    if not log_root.exists():
        print(f"log root not found: {log_root}")
        return 1

    run_dirs = []
    if args.run:
        run_dirs = [log_root / args.run]
    else:
        for p in sorted(log_root.iterdir()):
            if p.is_dir() and (p / "trajectory_pool.json").exists():
                run_dirs.append(p)

    print(f"Scanning {len(run_dirs)} run(s){' (DRY RUN)' if args.dry_run else ''}...")
    grand_patched = 0
    for d in run_dirs:
        print(f"\n=== {d.name} ===")
        r = patch_run(d, args.dry_run)
        print(f"  patched {r.get('patched', 0)}/{r.get('empty_before', '?')} empty (of {r.get('total', '?')} total)")
        grand_patched += r.get("patched", 0)

    print(f"\n{'Would patch' if args.dry_run else 'Patched'} {grand_patched} trajectories total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
