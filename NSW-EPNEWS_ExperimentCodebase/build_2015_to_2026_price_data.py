#!/usr/bin/env python3
"""Downsample 2025/2026 NSW price data and append it to 2015To2024Data.csv."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "CollectedData" / "Electricity prices from NEM" / "unified_price_data" / "unified_used_for_experiment" / "2015To2024Data.csv"
DEFAULT_ORIGINAL_ROOT = ROOT / "CollectedData" / "Electricity prices from NEM" / "original_price_data"
DEFAULT_OUTPUT = ROOT / "CollectedData" / "Electricity prices from NEM" / "unified_price_data" / "unified_used_for_experiment" / "2015To2026Data.csv"
DEFAULT_RAW_OUTPUT = ROOT / "NSW-EPNEWS_RawDatasetConstruct" / "2015To2026Data.csv"


def downsample_file(path: Path) -> pd.DataFrame:
    df_original = pd.read_csv(path, parse_dates=["SETTLEMENTDATE"])
    original_columns = df_original.columns.tolist()
    df = df_original.copy()
    df = df[df["REGION"] == "NSW1"]
    df.set_index("SETTLEMENTDATE", inplace=True)
    aggregation_rules = {
        "RRP": "median",
        "TOTALDEMAND": "mean",
        "REGION": "first",
        "PERIODTYPE": "first",
    }
    resampled = df.resample("30min", label="right", closed="right").agg(aggregation_rules)
    resampled.dropna(subset=["RRP", "TOTALDEMAND", "REGION"], inplace=True)
    resampled.reset_index(inplace=True)
    return resampled[original_columns]


def read_extension(original_root: Path, years: list[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        folder = original_root / str(year) / "NSW"
        for path in sorted(folder.glob("PRICE_AND_DEMAND_*_NSW1.csv")):
            frame = downsample_file(path)
            frames.append(frame)
            start = frame["SETTLEMENTDATE"].min()
            end = frame["SETTLEMENTDATE"].max()
            print(f"downsampled {path.name}: rows={len(frame)} range={start}..{end}")
    if not frames:
        raise FileNotFoundError(f"No NSW price files found for years={years} under {original_root}")
    extension = pd.concat(frames, ignore_index=True)
    extension.drop_duplicates(subset=["REGION", "SETTLEMENTDATE"], keep="last", inplace=True)
    extension.sort_values(["REGION", "SETTLEMENTDATE"], inplace=True)
    return extension


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 2015To2026Data.csv from existing 2015-2024 and 2025/2026 NSW data.")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--original-root", type=Path, default=DEFAULT_ORIGINAL_ROOT)
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    args = parser.parse_args()

    base = pd.read_csv(args.base)
    columns = ["REGION", "SETTLEMENTDATE", "TOTALDEMAND", "RRP", "PERIODTYPE"]
    if base.columns.tolist() != columns:
        raise ValueError(f"Unexpected base columns: {base.columns.tolist()}")

    extension = read_extension(args.original_root, args.years)
    extension["SETTLEMENTDATE"] = extension["SETTLEMENTDATE"].dt.strftime("%-d/%m/%Y %-H:%M")
    extension = extension[columns]

    merged = pd.concat([base, extension], ignore_index=True)
    merged.to_csv(args.output, index=False, encoding="utf-8-sig")
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.raw_output, index=False, encoding="utf-8-sig")

    print(f"base_rows={len(base)} extension_rows={len(extension)} merged_rows={len(merged)}")
    print(f"wrote={args.output}")
    print(f"wrote={args.raw_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
