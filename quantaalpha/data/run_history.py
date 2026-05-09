"""
Read past mining-run artifacts from the QA `log/` directory.

QA's backend doesn't persist task records across restarts — runs leave
their artifacts on disk under `log/<timestamp>/` (with
`trajectory_pool.json`, `evolution_state.json`, per-trajectory subdirs).
This module is the read-only side: walk the log dir, return summaries
+ full trajectory pools for the FE to render.

Mirrors the data shape QC's frontend expects (RunSummary + Trajectory)
so we can port the AnalysisCard component directly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from quantaalpha.log import logger


DEFAULT_LOG_ROOT = Path("log")


# ─── Walk the log dir ──────────────────────────────────────────────────────


def list_runs(log_root: Path | str = DEFAULT_LOG_ROOT) -> list[dict]:
    """Return summaries of every run dir under log_root, newest first."""
    root = Path(log_root)
    if not root.exists():
        return []
    summaries: list[dict] = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        # Skip non-run dirs (e.g. plain log files, system stuff)
        traj_pool = entry / "trajectory_pool.json"
        evo_state = entry / "evolution_state.json"
        if not traj_pool.exists() and not evo_state.exists():
            continue
        try:
            summaries.append(_summarize_run(entry))
        except Exception as exc:
            logger.warning(f"failed to summarize {entry.name}: {exc}")
            continue
    return summaries


def _summarize_run(run_dir: Path) -> dict:
    """Build a compact summary dict for one run."""
    traj_pool_path = run_dir / "trajectory_pool.json"
    evo_state_path = run_dir / "evolution_state.json"

    pool = {}
    if traj_pool_path.exists():
        try:
            pool = json.loads(traj_pool_path.read_text(encoding="utf-8"))
        except Exception:
            pool = {}
    state = {}
    if evo_state_path.exists():
        try:
            state = json.loads(evo_state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    trajs = list((pool.get("trajectories") or {}).values())
    by_phase: dict[str, int] = {}
    sharpes: list[float] = []
    rank_icirs: list[float] = []
    irs: list[float] = []
    for t in trajs:
        bm = t.get("backtest_metrics") or {}
        ph = t.get("phase") or "unknown"
        by_phase[ph] = by_phase.get(ph, 0) + 1
        ric = bm.get("RankICIR")
        ir = bm.get("information_ratio")
        if isinstance(ric, (int, float)):
            rank_icirs.append(float(ric))
        if isinstance(ir, (int, float)):
            irs.append(float(ir))

    cfg = state.get("config") or {}
    return {
        "run_id": run_dir.name,
        "log_dir": str(run_dir),
        "total_trajectories": len(trajs),
        "by_phase": by_phase,
        "best_rank_icir": max(rank_icirs) if rank_icirs else None,
        "best_ir": max(irs) if irs else None,
        "current_round": state.get("current_round"),
        "current_phase": state.get("current_phase"),
        "directions_completed": len(state.get("directions_completed") or []),
        "config": cfg,
        "saved_at": pool.get("saved_at"),
        # Best-effort created_at: parse from log dir name "YYYY-MM-DD_HH-MM-SS-microseconds"
        "created_at": _parse_run_dir_timestamp(run_dir.name),
    }


def _parse_run_dir_timestamp(name: str) -> Optional[str]:
    """QA log dir convention: YYYY-MM-DD_HH-MM-SS-microseconds → ISO."""
    parts = name.split("_")
    if len(parts) < 2:
        return None
    date = parts[0]
    rest = "_".join(parts[1:])
    # Replace dashes between time components with colons
    pieces = rest.split("-")
    if len(pieces) >= 3:
        time_str = ":".join(pieces[:3])
        return f"{date}T{time_str}"
    return None


def load_run(log_root: Path | str, run_id: str) -> dict:
    """Return the full run state: summary + all trajectories.

    Raises FileNotFoundError if the run doesn't exist.
    """
    run_dir = Path(log_root) / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"run not found: {run_dir}")
    summary = _summarize_run(run_dir)
    pool = {}
    pool_path = run_dir / "trajectory_pool.json"
    if pool_path.exists():
        try:
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
        except Exception:
            pool = {}
    return {
        "summary": summary,
        "pool": pool,
    }


# ─── Cached analysis (read-side) ────────────────────────────────────────────


def load_cached_analysis(log_root: Path | str, run_id: str) -> Optional[dict]:
    p = Path(log_root) / run_id / "analysis.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
