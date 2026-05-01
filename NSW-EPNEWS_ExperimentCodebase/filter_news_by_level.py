#!/usr/bin/env python3
"""Filter classified NSW-EPNews yearly CSV files by relevance level."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def extract_level(text: str) -> int | None:
    match = re.search(r"Level\s*([123])", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter classified news rows by relevance Level.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-level", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--keep-unknown", action="store_true")
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    kept = []
    counts = {1: 0, 2: 0, 3: 0, None: 0}
    for row in rows:
        level = extract_level(row.get("classified_content", ""))
        counts[level] = counts.get(level, 0) + 1
        if level is None:
            if args.keep_unknown:
                kept.append(row)
        elif level <= args.max_level:
            kept.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(f"input_rows={len(rows)} output_rows={len(kept)} output={args.output}")
    print(f"level_counts={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
