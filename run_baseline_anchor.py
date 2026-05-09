"""
Tier 4b: baseline-only anchor run.

Runs `conf_baseline.yaml` (Alpha158 20-feature subset, no mined factors) end-to-end
via qlib's qrun, then prints the IC / RankIC / ARR / MDD on the test window.

Use the printed numbers as the BASELINE — when we run the full mining loop later,
the delta in IC / ARR vs this baseline attributes cleanly to the mined factors.

Usage:
    .venv\\Scripts\\python.exe run_baseline_anchor.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
TEMPLATE = REPO_ROOT / "quantaalpha" / "factors" / "factor_template" / "conf_baseline.yaml"
QLIB_DATA_DIR = REPO_ROOT / "data" / "qlib" / "us_data"


def main() -> int:
    if not TEMPLATE.exists():
        print(f"[ERROR] template not found: {TEMPLATE}", file=sys.stderr)
        return 2
    if not QLIB_DATA_DIR.exists():
        print(f"[ERROR] qlib data dir not found: {QLIB_DATA_DIR}", file=sys.stderr)
        return 2

    workspace = Path(tempfile.mkdtemp(prefix="qa_baseline_"))
    print(f"[anchor] workspace: {workspace}")

    conf_path = workspace / "conf_baseline.yaml"
    shutil.copy2(TEMPLATE, conf_path)
    print(f"[anchor] copied template -> {conf_path}")
    print(f"[anchor] running qlib (this may take 1-3 minutes)...")

    # Use the venv's Scripts dir on PATH so qrun.exe is findable on Windows.
    import os
    env = os.environ.copy()
    venv_scripts = Path(sys.executable).parent
    env["PATH"] = str(venv_scripts) + os.pathsep + env.get("PATH", "")

    t0 = time.time()
    try:
        qrun_exe = venv_scripts / ("qrun.exe" if sys.platform == "win32" else "qrun")
        if not qrun_exe.exists():
            print(f"[ERROR] qrun not found at {qrun_exe}", file=sys.stderr)
            return 4
        result = subprocess.run(
            [str(qrun_exe), str(conf_path)],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        print("[ERROR] qrun timed out after 15 minutes", file=sys.stderr)
        return 3

    wall = time.time() - t0
    print(f"[anchor] qlib finished in {wall:.1f}s, exit={result.returncode}")

    if result.returncode != 0:
        print("[anchor] STDERR (last 60 lines):")
        for line in result.stderr.splitlines()[-60:]:
            print(f"  {line}")
        print("[anchor] STDOUT (last 30 lines):")
        for line in result.stdout.splitlines()[-30:]:
            print(f"  {line}")
        return result.returncode

    # Parse metrics from the qrun stdout. qlib prints lines like
    #   {'IC': 0.0123, 'ICIR': 0.0987, 'Rank IC': 0.0145, 'Rank ICIR': 0.1023}
    metrics = _parse_metrics(result.stdout)
    print()
    print("=" * 60)
    print("BASELINE ANCHOR — Alpha158 20-feature subset, no mined factors")
    print("=" * 60)
    if metrics:
        for k, v in metrics.items():
            print(f"  {k:20s} = {v}")
    else:
        print("[anchor] could not parse metrics; full stdout below:")
        print(result.stdout[-3000:])
    print("=" * 60)
    print()
    print("Use these numbers as the baseline. When the mining loop produces")
    print("conf_combined_factors numbers, the delta is the mined-factor uplift.")
    print(f"Workspace kept at: {workspace}")
    return 0


def _parse_metrics(stdout: str) -> dict:
    """Pull the metrics from qrun's printed dicts."""
    import re

    out: dict = {}
    # Try JSON-ish dict patterns
    for line in stdout.splitlines():
        for m in re.finditer(r"\{[^\}]+\}", line):
            blob = m.group(0)
            # qlib formats keys with quotes around them sometimes
            try:
                # cheap-and-cheerful
                blob_norm = blob.replace("'", '"')
                d = json.loads(blob_norm)
                if isinstance(d, dict) and any(
                    k in d for k in ("IC", "ICIR", "Rank IC", "RankIC", "annualized_return")
                ):
                    out.update(d)
            except Exception:
                continue

    # Common qlib backtest output line, e.g. "annualized_return ... 0.123"
    for line in stdout.splitlines():
        for key in (
            "annualized_return",
            "max_drawdown",
            "information_ratio",
            "excess_return_without_cost",
            "excess_return_with_cost",
        ):
            if key in line:
                m = re.search(r"-?\d+\.\d+", line)
                if m:
                    out.setdefault(key, float(m.group(0)))

    return out


if __name__ == "__main__":
    raise SystemExit(main())
