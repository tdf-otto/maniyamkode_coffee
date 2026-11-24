#!/usr/bin/env python3
"""Nightly/on-update analysis: recompute week-of-year baselines, flags, and
CUSUM breakpoints. Run standalone (`python scripts/analyze.py`) or via
preload/update.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_analysis() -> dict:
    from app.services.baselines import recompute_baselines
    from app.services.breaks import recompute_breakpoints
    from app.services.flags import recompute_flags

    n_base = recompute_baselines()
    print(f"[analyze] baselines: {n_base} (plot, series, week) cells")
    n_flags = recompute_flags()
    print(f"[analyze] flags: {n_flags} active")
    n_bp = recompute_breakpoints()
    print(f"[analyze] breakpoints: {n_bp} detected")
    return {"baselines": n_base, "flags": n_flags, "breakpoints": n_bp}


def main() -> None:
    run_analysis()


if __name__ == "__main__":
    main()
