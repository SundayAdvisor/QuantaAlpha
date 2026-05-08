"""
Factor pool admission filter (paper §5.5 case-study setup).

Implements the greedy, RankIC-sorted admission rule with correlation gating
and a 50%-of-mined cap. Without this filter, the cumulative factor pool fills
up with redundant near-duplicates and the model's reward signal becomes
contaminated by repeated information channels.

Rule:
  1. Sort all candidates by RankIC desc.
  2. Walk down the list; for each candidate, admit only if |corr| < threshold
     against every already-admitted member.
  3. After greedy admission, trim to top `cap_ratio * total_candidates` by RankIC.

Correlation here is the average cross-sectional correlation of factor values
(per-day pearson between stocks, averaged across days). Pooled correlation
would be inflated by time-trends shared by all factors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from quantaalpha.log import logger


@dataclass
class FactorCandidate:
    """One factor up for admission."""
    name: str
    rank_ic: float
    values: pd.Series  # MultiIndex (datetime, instrument), value = factor score


def average_xs_correlation(f1: pd.Series, f2: pd.Series, min_stocks: int = 5) -> float:
    """
    Average cross-sectional correlation between two factor panels.

    Both Series are expected to be indexed by MultiIndex (datetime, instrument).
    For each day in the shared index, compute Pearson correlation across stocks,
    then average.
    """
    if not isinstance(f1.index, pd.MultiIndex) or not isinstance(f2.index, pd.MultiIndex):
        c = f1.corr(f2)
        return 0.0 if pd.isna(c) else float(c)

    df = pd.concat([f1.rename("a"), f2.rename("b")], axis=1, join="inner").dropna()
    if df.empty:
        return 0.0

    # Group on the first level (datetime) and corr per day
    def _day_corr(g: pd.DataFrame) -> float:
        if len(g) < min_stocks:
            return np.nan
        return g["a"].corr(g["b"])

    daily = df.groupby(level=0, group_keys=False).apply(_day_corr).dropna()
    if daily.empty:
        return 0.0
    return float(daily.mean())


class FactorAdmissionFilter:
    """
    Greedy RankIC-sorted admission with correlation gating and pool cap.

    Usage:
        flt = FactorAdmissionFilter(corr_threshold=0.7, cap_ratio=0.5)
        admitted = flt.filter(candidates)
    """

    def __init__(
        self,
        corr_threshold: float = 0.7,
        cap_ratio: float = 0.5,
        min_stocks: int = 5,
    ):
        if not 0.0 < corr_threshold <= 1.0:
            raise ValueError(f"corr_threshold must be in (0, 1], got {corr_threshold}")
        if not 0.0 < cap_ratio <= 1.0:
            raise ValueError(f"cap_ratio must be in (0, 1], got {cap_ratio}")
        self.corr_threshold = corr_threshold
        self.cap_ratio = cap_ratio
        self.min_stocks = min_stocks

    def filter(self, candidates: list[FactorCandidate]) -> list[FactorCandidate]:
        if not candidates:
            return []

        sorted_cands = sorted(
            candidates,
            key=lambda c: c.rank_ic if c.rank_ic is not None else float("-inf"),
            reverse=True,
        )

        admitted: list[FactorCandidate] = []
        rejected_count = 0
        for cand in sorted_cands:
            if cand.rank_ic is None or pd.isna(cand.rank_ic):
                rejected_count += 1
                continue
            if self._can_admit(cand, admitted):
                admitted.append(cand)
            else:
                rejected_count += 1

        cap = max(1, int(round(len(candidates) * self.cap_ratio)))
        if len(admitted) > cap:
            admitted = admitted[:cap]

        logger.info(
            f"Admission filter: {len(candidates)} candidates → "
            f"{len(admitted)} admitted, {rejected_count} rejected, "
            f"cap={cap} ({self.cap_ratio*100:.0f}% of mined), "
            f"corr_threshold={self.corr_threshold}"
        )
        return admitted

    def _can_admit(
        self, candidate: FactorCandidate, pool: list[FactorCandidate]
    ) -> bool:
        if not pool:
            return True
        for member in pool:
            try:
                corr = average_xs_correlation(
                    candidate.values, member.values, self.min_stocks
                )
            except Exception as e:
                logger.warning(
                    f"Correlation calc failed for {candidate.name} vs "
                    f"{member.name}: {e}; treating as non-redundant"
                )
                continue
            if abs(corr) >= self.corr_threshold:
                logger.debug(
                    f"Rejecting {candidate.name}: |corr| {abs(corr):.3f} >= "
                    f"{self.corr_threshold} vs {member.name}"
                )
                return False
        return True


def filter_factor_panel(
    factor_panel: pd.DataFrame,
    rank_ics: dict[str, float],
    corr_threshold: float = 0.7,
    cap_ratio: float = 0.5,
) -> list[str]:
    """
    Convenience wrapper: take a wide factor DataFrame (columns = factor names,
    MultiIndex rows = (datetime, instrument)) and a {name: rank_ic} dict,
    return the list of admitted factor column names.
    """
    candidates: list[FactorCandidate] = []
    for col in factor_panel.columns:
        ric = rank_ics.get(col)
        if ric is None or pd.isna(ric):
            continue
        candidates.append(
            FactorCandidate(name=col, rank_ic=float(ric), values=factor_panel[col])
        )

    flt = FactorAdmissionFilter(corr_threshold=corr_threshold, cap_ratio=cap_ratio)
    admitted = flt.filter(candidates)
    return [c.name for c in admitted]


def apply_default_admission(
    factor_panel: pd.DataFrame,
    rank_ics: Optional[dict[str, float]] = None,
    corr_threshold: float = 0.7,
    cap_ratio: float = 0.5,
) -> pd.DataFrame:
    """
    Apply admission rule to a factor panel and return the filtered panel.

    When `rank_ics` is supplied, runs the full paper §5.5 rule:
    greedy RankIC-sorted admission with |corr| < threshold and 50% cap.

    When `rank_ics` is None or partially populated, falls back to greedy
    admission in current column order (assumes upstream ordering reflects
    quality — e.g. SOTA factors first, then new factors).

    Args:
        factor_panel: wide DataFrame, columns = factor names, MultiIndex
            rows = (datetime, instrument).
        rank_ics: optional {factor_name: rank_ic} mapping.
        corr_threshold: pairwise correlation threshold (default 0.7).
        cap_ratio: keep at most cap_ratio * total candidates (default 0.5).

    Returns:
        Filtered DataFrame with only admitted columns.
    """
    if factor_panel.empty or len(factor_panel.columns) == 0:
        return factor_panel

    rank_ics = rank_ics or {}

    candidates: list[FactorCandidate] = []
    for col in factor_panel.columns:
        ric = rank_ics.get(col)
        if ric is None or pd.isna(ric):
            ric = 0.0  # placeholder so column-order tie-break kicks in
        candidates.append(
            FactorCandidate(name=col, rank_ic=float(ric), values=factor_panel[col])
        )

    flt = FactorAdmissionFilter(corr_threshold=corr_threshold, cap_ratio=cap_ratio)
    admitted = flt.filter(candidates)
    admitted_names = [c.name for c in admitted]
    return factor_panel.loc[:, admitted_names]
