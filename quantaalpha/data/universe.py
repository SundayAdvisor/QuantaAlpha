"""
Universe + calendar discovery for QA — single source of truth.

Reads the qlib data on disk to enumerate:
  - Available instruments (SP500 / Nasdaq100 / "all" lists, plus per-ticker
    feature directories actually present)
  - Available date range (from calendars/day.txt)
  - Available features (close / open / high / low / volume / etc.)

Used by the planning agent + objective suggester so the LLM only proposes
factor-mining directions on tickers + dates that actually exist on disk.

Sister of `repos/QuantaQC/quantqc/data/universe.py` — same idea, but qlib
format instead of Lean format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


DEFAULT_QLIB_ROOT = Path("data/qlib/us_data")


def _read_instruments(instruments_file: Path) -> list[str]:
    """Parse a qlib instruments file. Format: TICKER<TAB>start_date<TAB>end_date."""
    if not instruments_file.exists():
        return []
    out: list[str] = []
    for line in instruments_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            out.append(parts[0].upper())
    return out


def _read_calendar(calendar_file: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (first_date, last_date) from a qlib calendar file, or (None, None)."""
    if not calendar_file.exists():
        return None, None
    lines = [
        ln.strip()
        for ln in calendar_file.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    if not lines:
        return None, None
    return lines[0], lines[-1]


def list_universe(
    qlib_root: Path | str = DEFAULT_QLIB_ROOT,
    *,
    universe: str = "sp500",
) -> dict[str, Any]:
    """Return universe info for QA.

    Args:
        qlib_root: path to qlib data root (default `data/qlib/us_data`)
        universe: one of "sp500", "nasdaq100", "all" — selects the
            instruments file. If the file isn't found, falls back to
            walking the features/ dir directly.

    Returns:
        {
            "universe": "sp500",
            "tickers": ["MMM", "ABT", ...],     # uppercase
            "n_tickers": 755,
            "n_with_data": 720,                 # tickers that ALSO have a feature dir
            "earliest_date": "1999-12-31",
            "latest_date":   "2020-11-10",
            "features":      ["close", "open", "high", ...],
        }
    """
    qroot = Path(qlib_root)
    instruments_file = qroot / "instruments" / f"{universe}.txt"

    tickers = _read_instruments(instruments_file)
    if not tickers:
        # Fallback: walk features/ directly. This catches the case where
        # the user has data but no instruments file.
        features_dir = qroot / "features"
        if features_dir.exists():
            tickers = [
                p.name.upper()
                for p in sorted(features_dir.iterdir())
                if p.is_dir() and not p.name.startswith("_")
            ]

    # Cross-check: which of those declared tickers actually have feature data?
    features_dir = qroot / "features"
    with_data: list[str] = []
    available_features: set[str] = set()
    if features_dir.exists():
        present = {p.name.lower() for p in features_dir.iterdir() if p.is_dir()}
        for t in tickers:
            if t.lower() in present:
                with_data.append(t)
        # Sample one ticker's features to see what's available
        if with_data:
            sample_dir = features_dir / with_data[0].lower()
            available_features = {
                p.stem
                for p in sample_dir.iterdir()
                if p.suffix in (".bin", ".day.bin")
            }

    earliest, latest = _read_calendar(qroot / "calendars" / "day.txt")

    return {
        "universe": universe,
        "tickers": tickers,
        "n_tickers": len(tickers),
        "n_with_data": len(with_data),
        "earliest_date": earliest,
        "latest_date": latest,
        "features": sorted(available_features),
    }


def list_available_universes(qlib_root: Path | str = DEFAULT_QLIB_ROOT) -> list[str]:
    """Return the names of `*.txt` files in the instruments dir."""
    inst_dir = Path(qlib_root) / "instruments"
    if not inst_dir.exists():
        return []
    return sorted(p.stem for p in inst_dir.glob("*.txt"))


def format_universe_for_prompt(
    qlib_root: Path | str = DEFAULT_QLIB_ROOT,
    *,
    universe: str = "sp500",
    sample_n: int = 50,
) -> str:
    """Render a compact universe summary for inclusion in LLM prompts.

    Includes ticker count + date range + a sample of N tickers (so the
    prompt isn't gigantic for the 755-ticker SP500 case).
    """
    info = list_universe(qlib_root, universe=universe)
    if not info["tickers"]:
        return f"(no qlib data found for universe '{universe}' at {qlib_root})"
    sample = info["tickers"][:sample_n]
    extra = info["n_tickers"] - len(sample)
    parts = [
        f"Universe: {info['universe']} — {info['n_tickers']} declared, "
        f"{info['n_with_data']} with feature data on disk.",
        f"Date range: {info['earliest_date']} to {info['latest_date']}.",
        f"Features: {', '.join(info['features']) if info['features'] else '(unknown)'}.",
        "Sample tickers (first {} of {}):".format(len(sample), info["n_tickers"]),
        ", ".join(sample) + (f", ...+{extra} more" if extra > 0 else ""),
    ]
    return "\n".join(parts)
