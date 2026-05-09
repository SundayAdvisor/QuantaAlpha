#!/usr/bin/env python3
"""
Publish top-N factor-mining trajectories from a completed QA run into a
separate findings repo. Each finding gets its own folder with the factor
expression(s), spec, full IC/IR table, and provenance.

Sister of `repos/QuantaQC/scripts/publish_findings.py` — same shape,
QA-flavored metrics + factor-expression artifact instead of Lean code.

Layout produced in the findings repo:

    quantaalpha-findings/
    ├── README.md
    ├── findings_config.json        # quality gates (auto-created)
    ├── registry.md                 # ledger
    └── factors/
        └── <factor_slug>/
            ├── factor.json         # expression + parameters
            ├── spec.md             # hypothesis + objective + metrics
            ├── results.md          # full Lean stats table
            └── provenance.json     # source run + trajectory ID

Usage (manual):
    python scripts/publish_findings.py --run RUN_ID
    python scripts/publish_findings.py --run RUN_ID --no-push
    python scripts/publish_findings.py --run RUN_ID --findings-repo PATH
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_ROOT = REPO_ROOT / "log"


DEFAULT_GATES = {
    "min_rank_icir": 0.05,
    "min_information_ratio": 0.0,
    "max_drawdown_cutoff": -0.40,
    "top_n": 5,
}


# ─── Findings-repo bootstrap ────────────────────────────────────────────────


def ensure_findings_repo(findings_root: Path) -> dict:
    findings_root.mkdir(parents=True, exist_ok=True)
    (findings_root / "factors").mkdir(parents=True, exist_ok=True)
    cfg_path = findings_root / "findings_config.json"
    if not cfg_path.exists():
        cfg_path.write_text(json.dumps(DEFAULT_GATES, indent=2), encoding="utf-8")
    try:
        gates = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        gates = dict(DEFAULT_GATES)
    readme = findings_root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# QuantaAlpha findings\n\n"
            "Auto-published top factor-mining trajectories from QuantaAlpha runs "
            "that pass the quality gates in `findings_config.json`. Each factor "
            "folder contains the factor expression(s), spec, IC/IR table, and "
            "full provenance back to the source mining run + trajectory.\n",
            encoding="utf-8",
        )
    registry = findings_root / "registry.md"
    if not registry.exists():
        registry.write_text(
            "# Findings registry\n\n"
            "| Slug | Source run | RankICIR | RankIC | IR | ARR | MaxDD | Date |\n"
            "|------|------------|---------:|-------:|---:|----:|------:|------|\n",
            encoding="utf-8",
        )
    return gates


# ─── Run loader ─────────────────────────────────────────────────────────────


def load_run(run_id: str) -> tuple[dict, list[dict], dict]:
    """Return (state, trajectories, pool)."""
    run_dir = LOG_ROOT / run_id
    if not run_dir.exists():
        raise SystemExit(f"run not found: {run_dir}")
    pool_path = run_dir / "trajectory_pool.json"
    if not pool_path.exists():
        raise SystemExit(f"no trajectory_pool.json for {run_id}")
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    trajs = list((pool.get("trajectories") or {}).values())
    state_path = run_dir / "evolution_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return state, trajs, pool


# ─── Selection ─────────────────────────────────────────────────────────────


def _fnum(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _metrics(t: dict) -> dict:
    bm = t.get("backtest_metrics") or {}
    return {
        "rank_ic": _fnum(bm.get("RankIC")),
        "rank_icir": _fnum(bm.get("RankICIR")),
        "ic": _fnum(bm.get("IC")),
        "icir": _fnum(bm.get("ICIR")),
        "ir": _fnum(bm.get("information_ratio")),
        "arr": _fnum(bm.get("annualized_return")),
        "drawdown": _fnum(bm.get("max_drawdown")),
    }


def passes_gates(m: dict, gates: dict) -> tuple[bool, list[str]]:
    failed: list[str] = []
    ric = m.get("rank_icir")
    if ric is None or ric < gates["min_rank_icir"]:
        failed.append(f"rank_icir {ric} < {gates['min_rank_icir']}")
    ir = m.get("ir")
    if gates.get("min_information_ratio") is not None and ir is not None:
        if ir < gates["min_information_ratio"]:
            failed.append(f"ir {ir:.3f} < {gates['min_information_ratio']}")
    dd = m.get("drawdown")
    cutoff = gates.get("max_drawdown_cutoff")
    if cutoff is not None and dd is not None and dd < cutoff:
        failed.append(f"drawdown {dd} < cutoff {cutoff}")
    return len(failed) == 0, failed


def select_top_n(trajs: list[dict], gates: dict) -> list[tuple[dict, dict]]:
    scored: list[tuple[dict, dict]] = []
    for t in trajs:
        m = _metrics(t)
        ok, _ = passes_gates(m, gates)
        if not ok:
            continue
        scored.append((t, m))
    scored.sort(
        key=lambda pair: pair[1].get("rank_icir") or -1e9,
        reverse=True,
    )
    return scored[: gates.get("top_n", 5)]


# ─── Slug + writers ────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def make_slug(traj: dict) -> str:
    name = traj.get("hypothesis", "")[:40] or "factor"
    base = _SLUG_RE.sub("-", name.lower()).strip("-")[:60] or "factor"
    return f"{base}-{(traj.get('trajectory_id') or '')[:8]}"


def write_factor_json(folder: Path, traj: dict) -> None:
    factors = traj.get("factors") or []
    payload = {
        "trajectory_id": traj.get("trajectory_id"),
        "factors": factors,
        "hypothesis": traj.get("hypothesis"),
    }
    (folder / "factor.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def write_spec_md(folder: Path, slug: str, traj: dict, m: dict, run_id: str) -> None:
    def _cell(v: Optional[float], fmt: str) -> str:
        if v is None:
            return "n/a"
        if fmt == "pct":
            return f"{v:.3%}"
        return f"{v:{fmt}}"

    rank_icir_cell = _cell(m["rank_icir"], ".4f")
    rank_ic_cell = _cell(m["rank_ic"], ".4f")
    ir_cell = _cell(m["ir"], ".3f")
    arr_cell = _cell(m["arr"], "pct")
    dd_cell = _cell(m["drawdown"], "pct")
    body = [
        f"# {slug}",
        "",
        "_Auto-published QuantaAlpha finding._",
        "",
        f"**Source run**: {run_id}",
        f"**Trajectory**: {traj.get('trajectory_id')}",
        f"**Phase**: {traj.get('phase')}, **round**: {traj.get('round_idx')}, "
        f"**direction**: {traj.get('direction_id')}",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| RankICIR | {rank_icir_cell} |",
        f"| RankIC | {rank_ic_cell} |",
        f"| IR | {ir_cell} |",
        f"| ARR | {arr_cell} |",
        f"| MaxDD | {dd_cell} |",
        "",
        "## Hypothesis",
        "",
        (traj.get("hypothesis") or "(no hypothesis)").strip(),
    ]
    (folder / "spec.md").write_text("\n".join(body) + "\n", encoding="utf-8")


def write_results_md(folder: Path, traj: dict) -> None:
    bm = traj.get("backtest_metrics") or {}
    rows = ["# Results", "", "| Metric | Value |", "|---|---|"]
    for k, v in bm.items():
        rows.append(f"| {k} | {v} |")
    (folder / "results.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_provenance_json(folder: Path, slug: str, traj: dict, run_id: str) -> None:
    payload = {
        "slug": slug,
        "source_run_id": run_id,
        "trajectory_id": traj.get("trajectory_id"),
        "phase": traj.get("phase"),
        "round_idx": traj.get("round_idx"),
        "direction_id": traj.get("direction_id"),
        "parent_ids": traj.get("parent_ids") or [],
        "extra_info": traj.get("extra_info") or {},
        "published_at": datetime.now().isoformat(),
    }
    (folder / "provenance.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def append_registry_row(findings_root: Path, slug: str, run_id: str, m: dict) -> None:
    parts = ["| `", slug, "` | ", run_id]
    parts += [" | " + (f"{m['rank_icir']:.4f}" if m["rank_icir"] is not None else "-")]
    parts += [" | " + (f"{m['rank_ic']:.4f}" if m["rank_ic"] is not None else "-")]
    parts += [" | " + (f"{m['ir']:.3f}" if m["ir"] is not None else "-")]
    parts += [" | " + (f"{m['arr']:.2%}" if m["arr"] is not None else "-")]
    parts += [" | " + (f"{m['drawdown']:.2%}" if m["drawdown"] is not None else "-")]
    parts += [" | " + datetime.now().strftime("%Y-%m-%d") + " |\n"]
    line = "".join(parts)
    with (findings_root / "registry.md").open("a", encoding="utf-8") as f:
        f.write(line)


# ─── Git ────────────────────────────────────────────────────────────────────


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout)[:500]}"
        )
    return proc.stdout


def commit_and_push(findings_root: Path, summary: str, push: bool, paths: list[str]) -> bool:
    if not (findings_root / ".git").exists():
        print(
            f"!! {findings_root} is not a git repo — skipping commit/push.",
            file=sys.stderr,
        )
        return False
    git(findings_root, "add", "--", *paths)
    diff = git(findings_root, "diff", "--cached", "--name-only").strip()
    if not diff:
        print("nothing new to commit")
        return False
    git(findings_root, "commit", "-m", summary)
    if push:
        git(findings_root, "push")
    return True


# ─── Main ───────────────────────────────────────────────────────────────────


def publish_run(run_id: str, findings_root: Path, *, push: bool, force: bool) -> int:
    state, trajs, pool = load_run(run_id)
    gates = ensure_findings_repo(findings_root)
    selected = select_top_n(trajs, gates)
    print(f"run {run_id}: {len(trajs)} candidates, {len(selected)} pass gates (top {gates.get('top_n')})")

    if not selected:
        print("no findings to publish")
        return 0

    new_paths: list[str] = []
    new_slugs: list[str] = []
    headline_summary: list[str] = []

    for traj, m in selected:
        slug = make_slug(traj)
        folder = findings_root / "factors" / slug
        if folder.exists() and not force:
            print(f"== {slug}: already published, skipping")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        write_factor_json(folder, traj)
        write_spec_md(folder, slug, traj, m, run_id)
        write_results_md(folder, traj)
        write_provenance_json(folder, slug, traj, run_id)
        append_registry_row(findings_root, slug, run_id, m)
        ric = m["rank_icir"]
        ir = m["ir"]
        head = (
            f"{slug} (RankICIR={ric:.3f}" if ric is not None else f"{slug} (RankICIR=n/a"
        ) + (f", IR={ir:.2f})" if ir is not None else ")")
        headline_summary.append(head)
        new_paths.append(f"factors/{slug}")
        new_slugs.append(slug)
        print(f"++ {slug}")

    if not new_slugs:
        print("nothing newly published")
        return 0

    new_paths += ["registry.md", "findings_config.json", "README.md"]
    summary = (
        f"add: {len(new_slugs)} finding(s) from run {run_id}\n\n"
        + "\n".join(f"  - {h}" for h in headline_summary)
    )
    committed = commit_and_push(findings_root, summary, push=push, paths=new_paths)
    if committed:
        print(f"committed{' + pushed' if push else ''}: {len(new_slugs)} folder(s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", required=True, help="QA run_id (log dir name)")
    ap.add_argument(
        "--findings-repo",
        default=os.environ.get("FINDINGS_REPO"),
        help="Local path to findings repo (or FINDINGS_REPO env var)",
    )
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not args.findings_repo:
        print(
            "!! findings repo path required: --findings-repo PATH or FINDINGS_REPO env var",
            file=sys.stderr,
        )
        return 2
    findings_root = Path(args.findings_repo).resolve()
    push = not args.no_push and (
        os.environ.get("FINDINGS_AUTO_PUSH", "1") not in {"0", "false", "False"}
    )
    return publish_run(args.run, findings_root, push=push, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
