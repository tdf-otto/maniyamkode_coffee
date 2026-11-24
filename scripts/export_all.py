#!/usr/bin/env python3
"""Export everything: one zip with all tables as CSV, plots GeoJSON, schema.

Usage:  python scripts/export_all.py [--out path.zip]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.export import export_all_zip  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    path = export_all_zip(args.out)
    print(f"export written: {path}")


if __name__ == "__main__":
    main()
