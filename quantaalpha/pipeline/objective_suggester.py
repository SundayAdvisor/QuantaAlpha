"""
LLM-driven factor-mining objective suggester for QA.

Reads the live qlib universe + recent runs and proposes 3-5 concrete
factor-mining directions the user can paste into the home-page objective
field. Three styles:
  - gap-fill:    avoid redundancy with what they already explored
  - adventurous: unusual / experimental factor families
  - refinement:  build on the user's most successful past runs

Sister of `repos/QuantaQC/quantqc/pipeline/objective_suggester.py`. Same
shape, QA-flavored prompts (RankICIR / IC / IR vocabulary instead of
Sharpe / PSR).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from quantaalpha.data.universe import format_universe_for_prompt, list_universe
from quantaalpha.log import logger
from quantaalpha.llm.client import APIBackend


# Canonical mechanism families for QA factor mining
MECHANISMS = (
    "value-anchor",
    "momentum",
    "mean-reversion",
    "volatility-derived",
    "volume-derived",
    "cross-sectional",
    "regime-conditioned",
    "calendar-effect",
    "sector-neutral-composite",
    "fundamental-proxy",
)
COMPLEXITY = ("low", "medium", "high")


@dataclass
class SuggestedObjective:
    title: str
    description: str
    mechanism: str
    primary_features: list[str] = field(default_factory=list)  # close, volume, etc
    expected_horizon_days: Optional[int] = None
    complexity: str = "medium"
    rationale_for_user: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "mechanism": self.mechanism,
            "primary_features": self.primary_features,
            "expected_horizon_days": self.expected_horizon_days,
            "complexity": self.complexity,
            "rationale_for_user": self.rationale_for_user,
        }


# ─── Recent-runs context ────────────────────────────────────────────────────


def summarize_recent_runs(runs: list[dict], n: int = 10) -> list[dict]:
    """Reduce QA run summaries to compact (objective, outcome) tuples."""
    sorted_runs = sorted(
        runs,
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    out: list[dict] = []
    for r in sorted_runs[:n]:
        out.append({
            "run_id": (r.get("run_id") or "")[:30],
            "n_trajectories": r.get("total_trajectories"),
            "best_rank_icir": r.get("best_rank_icir"),
            "best_ir": r.get("best_ir"),
            "by_phase": r.get("by_phase"),
            "config": r.get("config"),
            "current_phase": r.get("current_phase"),
            "directions_completed": r.get("directions_completed"),
        })
    return out


# ─── Prompts ────────────────────────────────────────────────────────────────


_BASE_SYSTEM = """\
You are a senior quant researcher curating what factor-mining direction
the user should explore NEXT in QuantaAlpha. You see the available qlib
universe + the user's exploration history. You propose 3-5 CONCRETE
directions the user can paste into the mining form.

Hard rules (always apply):
1. Every direction MUST be runnable on the available qlib universe +
   features + date range listed below. Don't propose factors needing
   tickers, features, or windows outside what's available.
2. Each direction must be specific enough to mine — not "explore value
   factors," but "ZSCORE(book/price) over 252-day window, sector-neutral,
   126-day forward horizon."
3. Span DIFFERENT mechanism families across the batch — not 4 momentum
   variants.
4. Be honest about complexity. Multi-stage composites with regime gating
   are "high"; a single rolling window is "low."

Output STRICT JSON.
"""


_STYLE_GAP_FILL = """\
[STYLE — GAP-FILL]
Identify what's MISSING from the user's exploration history and propose
ideas that fill those gaps. If they've already mined sector-neutral
composites, do NOT propose another sector-neutral composite. Anchor each
rationale to "you haven't tried X yet." Stay within familiar mechanism
families — nothing radically experimental.
"""

_STYLE_ADVENTUROUS = """\
[STYLE — ADVENTUROUS]
Propose UNUSUAL, experimental factors the user is unlikely to have
considered. Acceptable: cross-sectional skew of intra-month moves,
turnover-of-turnover, volume-weighted momentum decompositions, calendar
effects (turn-of-month, FOMC weeks), liquidity-conditioned reversals,
asymmetric-vol gating, sector-relative-strength regime switches.

You do NOT need to avoid the user's prior runs. Each rationale should
explain what's INTERESTING or UNDER-EXPLORED. Bias toward HIGH complexity
in this mode — the trade-off for novelty is more uncertainty.
"""

_STYLE_REFINEMENT = """\
[STYLE — REFINEMENT]
Build on the user's most SUCCESSFUL past runs (highest best_rank_icir).
Take what already worked and propose meaningful improvements: tighter
universe filters, alternative neutralization (sector vs industry vs
custom), different rolling windows, additional risk controls, or
composing two winning ideas. Each rationale should reference the specific
past run by run_id and explain how this proposal extends it.

If no past run has best_rank_icir > 0.04, fall back to gap-fill style.
"""

_STYLE_DIVERSIFY = """\
[STYLE — DIVERSIFY]
Maximize MECHANISM SPREAD within this batch. Every suggestion must come
from a different mechanism family (no two momentum, no two volatility-
derived, etc.). Aim to cover as many of the available families as the
batch size allows. The user is exploring breadth — they'll pick which
direction to deepen later.
"""

_STYLE_FOCUSED = """\
[STYLE — FOCUSED]
Generate VARIANTS WITHIN A SINGLE MECHANISM. If a focus hint specifies
the mechanism, use it; otherwise pick the strongest mechanism from the
user's past runs (highest best_rank_icir family). Vary the parameters:
rolling-window length, the feature(s) used (close vs volume vs range),
neutralization, and conditioning gates — but keep all proposals in the
same family. The user wants to deepen one direction, not spread.
"""

_STYLE_CONTRARIAN = """\
[STYLE — CONTRARIAN]
Invert what has been working. If past winners are MOMENTUM, propose
MEAN-REVERSION variants. If past winners are LONG-WINDOW, propose
SHORT-WINDOW. If past winners are RAW PRICE, propose VOLUME or
volatility-derived. The premise: an ensemble of complementary anti-
correlated factors is more robust than a stack of similar winners. Each
rationale should name what it's contrasting against (cite a past
run_id) and explain the inversion.

If there are no past wins to invert, fall back to adventurous style.
"""

_STYLE_SIMPLIFY = """\
[STYLE — SIMPLIFY]
Propose LOW-COMPLEXITY factors only: single rolling window, single
feature, no nested compositions, no regime gating. Useful as a sanity
baseline and for interpretability checks. Set complexity="low" on every
suggestion. If the user has high-complexity past winners, propose
simpler analogs that capture the core mechanism without the bells and
whistles.
"""

_STYLE_COMPOSE = """\
[STYLE — COMPOSE]
Synthesize NEW factors by combining mechanisms from the user's TOP TWO
past runs (highest best_rank_icir). For example: if past run A was a
volatility-conditioned signal and past run B was a sector-neutral
composite, propose factors that are sector-neutral AND volatility-
conditioned. Each rationale must reference both parent run_ids and
explain the synthesis.

If fewer than two past runs have best_rank_icir > 0.03, fall back to
adventurous style.
"""

_STYLE_PROMPTS = {
    "gap-fill": _STYLE_GAP_FILL,
    "adventurous": _STYLE_ADVENTUROUS,
    "refinement": _STYLE_REFINEMENT,
    "diversify": _STYLE_DIVERSIFY,
    "focused": _STYLE_FOCUSED,
    "contrarian": _STYLE_CONTRARIAN,
    "simplify": _STYLE_SIMPLIFY,
    "compose": _STYLE_COMPOSE,
}


def _auto_pick_style(recent_runs: Optional[list[dict]]) -> str:
    """Choose a style based on run history.

    Heuristic ladder:
      - 0 past runs                                 → 'adventurous'
      - 1 winner (best_rank_icir > 0.04)            → 'refinement'
      - 2+ winners (best_rank_icir > 0.03 each)     → 'compose'
      - many runs, all weak (no winner)             → 'contrarian'
      - few runs, none promising                    → 'gap-fill'
    """
    if not recent_runs:
        return "adventurous"
    winners_strong = sum(
        1 for r in recent_runs
        if isinstance(r.get("best_rank_icir"), (int, float)) and r["best_rank_icir"] > 0.04
    )
    winners_moderate = sum(
        1 for r in recent_runs
        if isinstance(r.get("best_rank_icir"), (int, float)) and r["best_rank_icir"] > 0.03
    )
    if winners_moderate >= 2:
        return "compose"
    if winners_strong >= 1:
        return "refinement"
    if len(recent_runs) >= 5:
        return "contrarian"
    return "gap-fill"


_USER_TEMPLATE = """\
[AVAILABLE UNIVERSE]
{universe_block}

[USER'S RECENT RUNS — most recent first]
{runs_block}

[FOCUS HINT FROM USER]
{focus_hint}

Propose {n} CONCRETE factor-mining directions. Each must use only the
available universe + features. Span DIFFERENT mechanisms.

Output STRICT JSON:
{{
  "suggestions": [
    {{
      "title": "<short label, e.g. 'Volatility-conditioned mean reversion'>",
      "description": "<2-3 sentence paragraph the user could paste into the
                       direction textarea: includes mechanism, instruments
                       (universe), feature(s) used, rolling window, and
                       prediction horizon>",
      "mechanism": "value-anchor | momentum | mean-reversion | volatility-derived | volume-derived | cross-sectional | regime-conditioned | calendar-effect | sector-neutral-composite | fundamental-proxy",
      "primary_features": ["close", "volume", ...],
      "expected_horizon_days": <int forward-prediction horizon, e.g. 21 or 63 or 126>,
      "complexity": "low | medium | high",
      "rationale_for_user": "<one sentence: why this fits THIS user given history>"
    }}
  ]
}}
"""


# ─── Public API ─────────────────────────────────────────────────────────────


def suggest_objectives(
    qlib_root: Path | str,
    *,
    universe: str = "sp500",
    recent_runs: Optional[list[dict]] = None,
    focus_hint: Optional[str] = None,
    n_suggestions: int = 4,
    style: str = "auto",
) -> list[SuggestedObjective]:
    """Ask the LLM for `n_suggestions` factor-mining directions.

    `style="auto"` (default) picks gap-fill / adventurous / refinement based
    on the user's run history. Pass an explicit value to override.
    """
    if style == "auto":
        style = _auto_pick_style(recent_runs)
    universe_block = format_universe_for_prompt(qlib_root, universe=universe)
    runs_summary = summarize_recent_runs(recent_runs or [], n=10)
    runs_block = (
        json.dumps(runs_summary, indent=2)
        if runs_summary
        else "(no past runs — fresh user; suggest broadly across mechanisms)"
    )
    style_block = _STYLE_PROMPTS.get(style, _STYLE_GAP_FILL)
    system_prompt = _BASE_SYSTEM + "\n" + style_block

    user_prompt = _USER_TEMPLATE.format(
        universe_block=universe_block,
        runs_block=runs_block,
        focus_hint=(focus_hint.strip() if focus_hint and focus_hint.strip() else "(none)"),
        n=n_suggestions,
    )

    try:
        raw = APIBackend().build_messages_and_create_chat_completion(
            user_prompt=user_prompt, system_prompt=system_prompt, json_mode=True
        )
        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.error(f"[qa-suggester] LLM/parse failed: {e}")
        return []

    candidates = data.get("suggestions") or []
    if not isinstance(candidates, list):
        return []

    out: list[SuggestedObjective] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        try:
            mech = str(c.get("mechanism", "momentum"))
            if mech not in MECHANISMS:
                mech = "momentum"
            comp = str(c.get("complexity", "medium")).lower()
            if comp not in COMPLEXITY:
                comp = "medium"
            features = c.get("primary_features") or []
            if not isinstance(features, list):
                features = []
            out.append(SuggestedObjective(
                title=str(c.get("title", "")).strip()[:80],
                description=str(c.get("description", "")).strip()[:1000],
                mechanism=mech,
                primary_features=[str(f).lower() for f in features if isinstance(f, str)][:6],
                expected_horizon_days=(int(c["expected_horizon_days"])
                                       if isinstance(c.get("expected_horizon_days"), (int, float)) else None),
                complexity=comp,
                rationale_for_user=str(c.get("rationale_for_user", "")).strip()[:300],
            ))
        except Exception as exc:
            logger.warning(f"[qa-suggester] dropped bad candidate: {exc}")
            continue

    logger.info(f"[qa-suggester] returned {len(out)} suggestions ({style})")
    return out
