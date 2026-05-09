"""
LLM-backed run analyzer for QuantaAlpha.

Adapted from `repos/QuantaQC/quantqc/optimization/analysis.py`. QA's
metric vocabulary (RankICIR, IC, IR, drawdown) replaces QC's
(Sharpe, PSR, Calmar). The verdict taxonomy is the same:

    robust / promising / regime-fit / marginal / broken

The analysis answers questions like:
  - Is this factor robust or curve-fit?
  - Did mutation actually improve on its parents?
  - Why are some trajectories below gates?
  - What's the right next experiment?

Cached to `log/<run_id>/analysis.json` so subsequent reads are free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from quantaalpha.log import logger
from quantaalpha.llm.client import APIBackend


VERDICT_LABELS = {
    "robust": "Top trajectories show consistent metrics across rounds; mutation/crossover improved on parents",
    "promising": "Best trajectory is meaningfully better than baseline but evidence is thin (few rounds, low n)",
    "regime-fit": "RankICIR positive but IR / annualized return negative — predictive but not profitable",
    "marginal": "Best metrics are barely above noise; not deployable as-is",
    "broken": "Most trajectories failed gates / had negative metrics — re-scope the run",
}


@dataclass
class RunAnalysis:
    run_id: str
    verdict: str
    verdict_reason: str
    summary: str
    per_trajectory_notes: list[dict]   # [{trajectory_id, note}]
    recommended_next_steps: list[str]
    best_rank_icir: Optional[float] = None
    best_ir: Optional[float] = None
    rank_icir_to_ir_gap: Optional[float] = None    # avg(rank_icir > 0) when IR < 0 → curve-fit smell
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "summary": self.summary,
            "per_trajectory_notes": self.per_trajectory_notes,
            "recommended_next_steps": self.recommended_next_steps,
            "best_rank_icir": self.best_rank_icir,
            "best_ir": self.best_ir,
            "rank_icir_to_ir_gap": self.rank_icir_to_ir_gap,
            "created_at": self.created_at,
        }


# ─── Helpers ────────────────────────────────────────────────────────────────


def _fnum(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trajectory_summary(t: dict) -> dict:
    bm = t.get("backtest_metrics") or {}
    return {
        "id": (t.get("trajectory_id") or "")[:12],
        "phase": t.get("phase"),
        "round": t.get("round_idx"),
        "direction": t.get("direction_id"),
        "parent_ids": t.get("parent_ids") or [],
        "rank_ic": _fnum(bm.get("RankIC")),
        "rank_icir": _fnum(bm.get("RankICIR")),
        "ic": _fnum(bm.get("IC")),
        "icir": _fnum(bm.get("ICIR")),
        "ir": _fnum(bm.get("information_ratio")),
        "ann_ret": _fnum(bm.get("annualized_return")),
        "max_dd": _fnum(bm.get("max_drawdown")),
        "hypothesis": (t.get("hypothesis") or "")[:200],
    }


def _heuristic_verdict(summaries: list[dict]) -> tuple[str, dict]:
    """Rule-based pre-verdict. The LLM may override this."""
    rics = [s["rank_icir"] for s in summaries if s["rank_icir"] is not None]
    irs = [s["ir"] for s in summaries if s["ir"] is not None]
    best_ric = max(rics) if rics else None
    best_ir = max(irs) if irs else None
    # Curve-fit smell: positive RankICIR with negative IR across most trajectories
    pos_ric_neg_ir = sum(
        1 for s in summaries
        if (s["rank_icir"] or 0) > 0.03 and (s["ir"] or 0) < 0
    )
    fraction = pos_ric_neg_ir / max(1, len(summaries))

    if best_ric is None:
        return "broken", {"best_ric": None, "best_ir": None, "ric_ir_gap": None}
    if best_ric < 0.02:
        return "broken", {"best_ric": best_ric, "best_ir": best_ir, "ric_ir_gap": fraction}
    if fraction > 0.6:
        return "regime-fit", {"best_ric": best_ric, "best_ir": best_ir, "ric_ir_gap": fraction}
    if best_ric < 0.04 and (best_ir is None or best_ir < 0):
        return "marginal", {"best_ric": best_ric, "best_ir": best_ir, "ric_ir_gap": fraction}
    if best_ric > 0.06 and (best_ir or 0) > 0.3:
        return "robust", {"best_ric": best_ric, "best_ir": best_ir, "ric_ir_gap": fraction}
    return "promising", {"best_ric": best_ric, "best_ir": best_ir, "ric_ir_gap": fraction}


# ─── Prompts ────────────────────────────────────────────────────────────────


_SYSTEM = """\
You are reviewing a QuantaAlpha factor-mining run. The user wants an
honest verdict on whether the factors discovered are robust or curve-fit,
plus a short writeup a quant could read in 30 seconds.

Verdict must be ONE of:
  - "robust": Top RankICIR > 0.06 AND IR > 0.3 across multiple rounds; mutation improved on parents
  - "promising": Best metrics meaningfully positive but evidence thin (few rounds / few trajectories)
  - "regime-fit": Positive RankICIR but negative IR — factor predicts ranks but loses money in execution
  - "marginal": Best RankICIR < 0.04 AND IR ≤ 0 — barely above noise
  - "broken": Most trajectories failed gates / had negative RankICIR — re-scope the run

When reasoning:
  - RankICIR > 0.05 is meaningful; > 0.07 is strong for a single factor.
  - IR < 0 with positive RankICIR is the classic factor-mining gap: the
    factor RANKS stocks correctly but the simple top-decile portfolio
    loses money (turnover costs / sector mismatch / etc).
  - Mutation's value is whether it improved on its parent. If round 1
    mutations have higher RankICIR than round 0 originals, the operator
    is working.
  - Drawdown ratio OOS:train is not directly observable in QA today
    (no walk-forward), so call out that limitation.

Be concise. Quants read fast.
"""


_USER_TEMPLATE = """\
[RUN]
run_id: {run_id}
config: {config_block}

[OBJECTIVE / INITIAL DIRECTION]
{initial_direction}

[TRAJECTORIES — most-recent / highest first]
{trajectory_block}

[SUMMARY]
trajectories total: {n_total}
by phase: {by_phase}
best RankICIR: {best_ric}
best IR: {best_ir}
fraction with positive RankICIR but negative IR: {ric_ir_gap}
heuristic pre-verdict: {heuristic}

Output STRICT JSON:
{{
  "verdict": "robust" | "promising" | "regime-fit" | "marginal" | "broken",
  "verdict_reason": "<one sentence — the single biggest signal>",
  "summary": "<2-3 SHORT paragraphs. Reference specific RankICIR/IR/ARR
              numbers. Mention if mutation improved on parents. Be honest,
              not optimistic.>",
  "per_trajectory_notes": [
    {{"trajectory_id": "<short id>", "note": "<one sentence per top-3 trajectory>"}}
  ],
  "recommended_next_steps": [
    "<concrete action, e.g. 'add walk-forward IC validation', 'tighten the universe to high-volume names', 'add turnover penalty'>"
  ]
}}
"""


def _format_trajectory_block(summaries: list[dict], top_n: int = 12) -> str:
    """Sort by rank_icir desc, render compact one-line-per-trajectory."""
    sorted_s = sorted(
        summaries,
        key=lambda s: s["rank_icir"] if s["rank_icir"] is not None else -1e9,
        reverse=True,
    )[:top_n]
    lines = []
    for s in sorted_s:
        ric = f"{s['rank_icir']:.4f}" if s["rank_icir"] is not None else "n/a"
        ir = f"{s['ir']:.3f}" if s["ir"] is not None else "n/a"
        ar = f"{s['ann_ret']:.3f}" if s["ann_ret"] is not None else "n/a"
        dd = f"{s['max_dd']:.3f}" if s["max_dd"] is not None else "n/a"
        lines.append(
            f"  {s['id']}  {s['phase']}/r{s['round']}/dir{s['direction']}  "
            f"RankICIR={ric}  IR={ir}  ARR={ar}  DD={dd}  "
            f"parents={[p[:8] for p in s['parent_ids']]}  "
            f"{s['hypothesis'][:80]}"
        )
    return "\n".join(lines) if lines else "  (no trajectories)"


# ─── Public API ─────────────────────────────────────────────────────────────


def analyze_run(
    run_id: str,
    pool: dict,
    config: dict,
    initial_direction: str = "",
) -> RunAnalysis:
    """Compute deterministic signals + ask the LLM for a structured verdict."""
    trajs = list((pool.get("trajectories") or {}).values())
    summaries = [_trajectory_summary(t) for t in trajs]

    heuristic, signals = _heuristic_verdict(summaries)

    by_phase: dict[str, int] = {}
    for s in summaries:
        ph = s["phase"] or "unknown"
        by_phase[ph] = by_phase.get(ph, 0) + 1

    prompt = _USER_TEMPLATE.format(
        run_id=run_id,
        config_block=json.dumps(config, default=str)[:400],
        initial_direction=(initial_direction or "(unspecified)")[:300],
        trajectory_block=_format_trajectory_block(summaries),
        n_total=len(summaries),
        by_phase=dict(by_phase),
        best_ric=signals.get("best_ric"),
        best_ir=signals.get("best_ir"),
        ric_ir_gap=signals.get("ric_ir_gap"),
        heuristic=heuristic,
    )

    try:
        raw = APIBackend().build_messages_and_create_chat_completion(
            user_prompt=prompt, system_prompt=_SYSTEM, json_mode=True
        )
        # Try strict JSON parse first; fall back to lenient extract
        try:
            data = json.loads(raw)
        except Exception:
            import re
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.error(f"[run-analyze] LLM/parse failed: {e}")
        return RunAnalysis(
            run_id=run_id,
            verdict=heuristic,
            verdict_reason=f"LLM analysis failed: {e}; using heuristic verdict.",
            summary="Automated analysis unavailable. Inspect the trajectory pool directly.",
            per_trajectory_notes=[],
            recommended_next_steps=["Re-run analysis when LLM is available."],
            best_rank_icir=signals.get("best_ric"),
            best_ir=signals.get("best_ir"),
            rank_icir_to_ir_gap=signals.get("ric_ir_gap"),
        )

    verdict = str(data.get("verdict", heuristic))
    if verdict not in VERDICT_LABELS:
        verdict = heuristic
    notes = data.get("per_trajectory_notes") or []
    cleaned_notes = []
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, dict) and "note" in n:
                cleaned_notes.append({
                    "trajectory_id": str(n.get("trajectory_id", ""))[:30],
                    "note": str(n.get("note", ""))[:400],
                })
    next_steps = data.get("recommended_next_steps") or []
    if not isinstance(next_steps, list):
        next_steps = []
    cleaned_steps = [str(s)[:300] for s in next_steps if isinstance(s, str)][:8]

    return RunAnalysis(
        run_id=run_id,
        verdict=verdict,
        verdict_reason=str(data.get("verdict_reason", "") or "")[:300],
        summary=str(data.get("summary", "") or "")[:2000],
        per_trajectory_notes=cleaned_notes,
        recommended_next_steps=cleaned_steps,
        best_rank_icir=signals.get("best_ric"),
        best_ir=signals.get("best_ir"),
        rank_icir_to_ir_gap=signals.get("ric_ir_gap"),
    )


def save_analysis(log_root: Path | str, run_id: str, analysis: RunAnalysis) -> None:
    out = Path(log_root) / run_id / "analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(analysis.to_dict(), indent=2, default=str), encoding="utf-8")
