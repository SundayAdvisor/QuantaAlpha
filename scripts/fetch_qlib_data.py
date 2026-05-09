#!/usr/bin/env python3
"""
Fetch daily OHLCV from yfinance and write qlib binary format for QuantaAlpha.

QA's data bundle currently ends 2020-11-10. This tool extends it through
the present, and fills in any tickers missing from the SP500/Nasdaq100
universes.

qlib binary layout (what we produce):

    data/qlib/us_data/
    ├── calendars/
    │   └── day.txt                 # one YYYY-MM-DD per line, sorted
    ├── instruments/
    │   ├── sp500.txt               # TAB-separated: TICKER<TAB>start<TAB>end
    │   ├── nasdaq100.txt
    │   └── all.txt
    └── features/
        └── <ticker_lower>/
            ├── close.day.bin        # float32 LE binary
            ├── open.day.bin
            ├── high.day.bin
            ├── low.day.bin
            ├── volume.day.bin
            ├── factor.day.bin       # split/dividend factor (1.0 throughout for adjusted prices)
            └── change.day.bin       # close-to-close return

Each .bin file format:
    [start_idx (1 float32)] [N float32 values aligned to calendar[start_idx..start_idx+N]]

Adjusted prices (yfinance auto_adjust=True) are written as `close/open/high/low`,
and `factor` is set to 1.0 across all bars (because adjustment is already
baked in). This matches QA's existing convention and avoids the qlib
factor-file complexity.

Usage:
    python scripts/fetch_qlib_data.py --tickers SPY QQQ TLT
    python scripts/fetch_qlib_data.py --universe sp500 --start 2020-11-11 --end 2026-01-01
    python scripts/fetch_qlib_data.py --extend                  # extend existing data only
    python scripts/fetch_qlib_data.py --universe sp500 --rebuild  # full rebuild
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QLIB_ROOT = REPO_ROOT / "data" / "qlib" / "us_data"
DEFAULT_END = "2026-01-01"

QLIB_FEATURES = ("open", "high", "low", "close", "volume", "factor", "change")


# ─── Calendar handling ──────────────────────────────────────────────────────


def read_calendar(qlib_root: Path) -> list[str]:
    cal = qlib_root / "calendars" / "day.txt"
    if not cal.exists():
        return []
    return [ln.strip() for ln in cal.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_calendar(qlib_root: Path, dates: list[str]) -> None:
    cal_dir = qlib_root / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / "day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")


def merge_calendar(existing: list[str], new_dates: Iterable[str]) -> list[str]:
    """Union + sort. Both inputs must already be ISO YYYY-MM-DD."""
    s = set(existing)
    for d in new_dates:
        s.add(d)
    return sorted(s)


# ─── Binary feature writer ──────────────────────────────────────────────────


def write_feature_bin(
    bin_path: Path,
    *,
    start_idx: int,
    values: list[float],
) -> None:
    """Write a qlib feature binary: [start_idx as float32][N float32 values]."""
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    with bin_path.open("wb") as f:
        f.write(struct.pack("<f", float(start_idx)))
        for v in values:
            # qlib uses NaN for missing
            x = float("nan") if v is None else float(v)
            f.write(struct.pack("<f", x))


# ─── yfinance ingestion ─────────────────────────────────────────────────────


def fetch_ticker(ticker: str, start: str, end: str) -> Optional[list[dict]]:
    """Returns a list of {date, open, high, low, close, volume} dicts."""
    try:
        import yfinance as yf
    except ImportError:
        print("!! yfinance not installed. pip install yfinance", file=sys.stderr)
        return None
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            actions=False,
        )
    except Exception as e:
        print(f"!! {ticker}: download error: {e}", file=sys.stderr)
        return None
    if df.empty:
        return None
    # yfinance >=0.2.51 returns MultiIndex columns even for single ticker
    if getattr(df.columns, "nlevels", 1) > 1:
        df.columns = df.columns.get_level_values(0)
    rows: list[dict] = []
    for ts, row in df.iterrows():
        d = ts.strftime("%Y-%m-%d")
        try:
            rows.append(
                {
                    "date": d,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


# ─── Per-ticker write ───────────────────────────────────────────────────────


def write_ticker(
    qlib_root: Path,
    ticker: str,
    rows: list[dict],
    calendar: list[str],
) -> None:
    """Align rows to the (possibly larger) global calendar and write 7
    feature .bin files. Computes `change` as close-to-close pct return."""
    ticker_lc = ticker.lower()
    feat_dir = qlib_root / "features" / ticker_lc

    # Build a date -> row index for fast alignment
    by_date = {r["date"]: r for r in rows}
    dated = sorted(rows, key=lambda r: r["date"])
    if not dated:
        return
    first_date = dated[0]["date"]
    last_date = dated[-1]["date"]

    # Find start_idx in the global calendar
    cal_idx = {d: i for i, d in enumerate(calendar)}
    start_idx = cal_idx.get(first_date)
    end_idx = cal_idx.get(last_date)
    if start_idx is None or end_idx is None:
        # The ticker's date range isn't fully inside the calendar — skip.
        # Caller should have ensured the calendar is a superset.
        print(
            f"!! {ticker}: dates {first_date}..{last_date} not in calendar; "
            f"skipping (regenerate calendar first)",
            file=sys.stderr,
        )
        return

    # Align: build per-feature value arrays of length (end_idx - start_idx + 1)
    span = end_idx - start_idx + 1
    aligned = {f: [None] * span for f in QLIB_FEATURES}

    prev_close: Optional[float] = None
    for j in range(span):
        cal_date = calendar[start_idx + j]
        row = by_date.get(cal_date)
        if row is None:
            continue
        c = row["close"]
        aligned["open"][j] = row["open"]
        aligned["high"][j] = row["high"]
        aligned["low"][j] = row["low"]
        aligned["close"][j] = c
        aligned["volume"][j] = row["volume"]
        aligned["factor"][j] = 1.0  # adjusted-bars-as-raw convention
        if prev_close is not None and prev_close != 0:
            aligned["change"][j] = (c - prev_close) / prev_close
        prev_close = c

    for feat, vals in aligned.items():
        write_feature_bin(
            feat_dir / f"{feat}.day.bin",
            start_idx=start_idx,
            values=vals,
        )


# ─── Instruments file ──────────────────────────────────────────────────────


def upsert_instruments(
    qlib_root: Path,
    universe: str,
    ticker: str,
    start_date: str,
    end_date: str,
) -> None:
    """Append or update a ticker row in instruments/<universe>.txt."""
    inst_dir = qlib_root / "instruments"
    inst_dir.mkdir(parents=True, exist_ok=True)
    inst_file = inst_dir / f"{universe}.txt"
    rows: dict[str, tuple[str, str]] = {}
    if inst_file.exists():
        for line in inst_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                rows[parts[0].upper()] = (parts[1], parts[2])
            elif len(parts) >= 1:
                rows[parts[0].upper()] = (start_date, end_date)
    rows[ticker.upper()] = (start_date, end_date)
    out = "\n".join(
        f"{t}\t{s}\t{e}" for t, (s, e) in sorted(rows.items())
    )
    inst_file.write_text(out + "\n", encoding="utf-8")


# ─── Universe loaders ──────────────────────────────────────────────────────


def load_universe_tickers(qlib_root: Path, universe: str) -> list[str]:
    """Read instruments/<universe>.txt; return tickers."""
    inst_file = qlib_root / "instruments" / f"{universe}.txt"
    if not inst_file.exists():
        return []
    out: list[str] = []
    for line in inst_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            out.append(parts[0].upper())
    return out


# ─── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--tickers", nargs="*", help="Specific tickers to fetch (case-insensitive)"
    )
    ap.add_argument(
        "--universe",
        help="Fetch every ticker from instruments/<universe>.txt (e.g. sp500, nasdaq100, all)",
    )
    ap.add_argument(
        "--qlib-root",
        default=str(DEFAULT_QLIB_ROOT),
        help=f"qlib data root (default {DEFAULT_QLIB_ROOT})",
    )
    ap.add_argument(
        "--start", default=None, help="Start date YYYY-MM-DD (default: extend from current calendar tail + 1)"
    )
    ap.add_argument(
        "--end", default=DEFAULT_END, help=f"End date YYYY-MM-DD (default {DEFAULT_END})"
    )
    ap.add_argument(
        "--extend",
        action="store_true",
        help="Extend mode: only fetch from the current calendar's last_date+1 onward",
    )
    ap.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild mode: ignore existing data, fetch full range from --start",
    )
    args = ap.parse_args()

    qlib_root = Path(args.qlib_root).resolve()
    print(f"qlib root: {qlib_root}")

    # Resolve ticker list
    tickers: list[str] = []
    if args.universe:
        tickers.extend(load_universe_tickers(qlib_root, args.universe))
        if not tickers:
            print(
                f"!! universe '{args.universe}' has no instruments file; aborting",
                file=sys.stderr,
            )
            return 2
        print(f"universe '{args.universe}' has {len(tickers)} tickers")
    if args.tickers:
        tickers.extend(t.upper() for t in args.tickers)
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        u = t.strip().upper()
        if u and u not in seen:
            seen.add(u)
            unique.append(u)
    if not unique:
        ap.print_help()
        return 2

    # Resolve date range
    existing_cal = read_calendar(qlib_root)
    if args.extend:
        if not existing_cal:
            print("!! --extend but no existing calendar found; using --start instead", file=sys.stderr)
            start = args.start or "2020-11-11"
        else:
            cur_last = existing_cal[-1]
            cur_dt = datetime.fromisoformat(cur_last)
            start = (cur_dt + timedelta(days=1)).date().isoformat()
            print(f"extend mode: fetching from {start} (existing calendar ends {cur_last})")
    else:
        start = args.start or (existing_cal[-1] if existing_cal else "1999-12-31")

    end = args.end
    print(f"date range: {start} to {end}")
    print(f"fetching {len(unique)} ticker(s)...")
    print()

    # Pass 1: fetch all tickers, keep in memory (or in temp dir if RAM is a concern)
    fetched: dict[str, list[dict]] = {}
    failures: list[str] = []
    for i, ticker in enumerate(unique, 1):
        rows = fetch_ticker(ticker, start, end)
        if not rows:
            failures.append(ticker)
            print(f"  [{i}/{len(unique)}] {ticker}: FAILED")
            continue
        fetched[ticker] = rows
        print(f"  [{i}/{len(unique)}] {ticker}: {len(rows)} bars, {rows[0]['date']} to {rows[-1]['date']}")

    if not fetched:
        print("nothing fetched", file=sys.stderr)
        return 1

    # Build the merged calendar from union of all fetched dates + existing
    new_dates: set[str] = set()
    for rows in fetched.values():
        for r in rows:
            new_dates.add(r["date"])
    if args.rebuild:
        merged_cal = sorted(new_dates)
    else:
        merged_cal = merge_calendar(existing_cal, new_dates)

    print(f"\ncalendar: {len(existing_cal)} existing -> {len(merged_cal)} merged")
    write_calendar(qlib_root, merged_cal)

    # Pass 2: write per-ticker binaries against the merged calendar
    written = 0
    for ticker, rows in fetched.items():
        try:
            write_ticker(qlib_root, ticker, rows, merged_cal)
            # Update instruments file in the universe (if specified)
            if args.universe:
                upsert_instruments(
                    qlib_root,
                    args.universe,
                    ticker,
                    rows[0]["date"],
                    rows[-1]["date"],
                )
            written += 1
        except Exception as e:
            print(f"!! {ticker}: write error: {e}", file=sys.stderr)
            failures.append(ticker)

    print(f"\n=== done ===")
    print(f"wrote {written}/{len(unique)} tickers")
    if failures:
        print(f"failures: {', '.join(failures[:20])}{'...' if len(failures) > 20 else ''}")
    print(f"calendar: {merged_cal[0]} to {merged_cal[-1]} ({len(merged_cal)} days)")
    return 0 if not failures else (0 if written > 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
