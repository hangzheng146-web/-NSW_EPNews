#!/usr/bin/env python3
"""Append 2025/2026 BoM temperature files to existing max/min temp CSVs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "CollectedData" / "Temperature"


def normalize_station(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return str(int(text)) if text.isdigit() else text


def normalize_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df[columns].copy()
    df["Bureau of Meteorology station number"] = df["Bureau of Meteorology station number"].map(normalize_station)
    for col in ["Year", "Month", "Day"]:
        df[col] = pd.to_numeric(df[col], errors="raise").astype(int)
    return df


def build(kind: str, years: list[int], temp_root: Path) -> Path:
    if kind == "max":
        base_path = temp_root / "max_temps.csv"
        output_path = temp_root / "max_temps_2015_2026.csv"
        product = "IDCJAC0010"
    elif kind == "min":
        base_path = temp_root / "min_temps.csv"
        output_path = temp_root / "min_temps_2015_2026.csv"
        product = "IDCJAC0011"
    else:
        raise ValueError(kind)

    base = pd.read_csv(base_path)
    columns = base.columns.tolist()
    base = normalize_frame(base, columns)

    frames = [base]
    for year in years:
        pattern = f"{product}_*_{year}/{product}_*_{year}_Data.csv"
        paths = sorted((temp_root / "temperature" / kind).glob(pattern))
        if not paths:
            print(f"{kind} {year}: no files found for {pattern}")
        for path in paths:
            df = pd.read_csv(path)
            df = normalize_frame(df, columns)
            frames.append(df)
            stations = sorted(df["Bureau of Meteorology station number"].unique().tolist())
            print(f"{kind} loaded {path}: rows={len(df)} stations={stations}")

    merged = pd.concat(frames, ignore_index=True)
    merged.drop_duplicates(
        subset=["Product code", "Bureau of Meteorology station number", "Year", "Month", "Day"],
        keep="last",
        inplace=True,
    )
    merged.sort_values(["Year", "Month", "Day", "Bureau of Meteorology station number"], inplace=True)
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"{kind}: base_rows={len(base)} merged_rows={len(merged)} output={output_path}")
    return output_path


def trim_min_to_max_end(temp_root: Path) -> None:
    max_path = temp_root / "max_temps_2015_2026.csv"
    min_path = temp_root / "min_temps_2015_2026.csv"
    max_df = pd.read_csv(max_path)
    min_df = pd.read_csv(min_path)
    max_end = max_df[["Year", "Month", "Day"]].drop_duplicates().sort_values(["Year", "Month", "Day"]).tail(1).iloc[0]
    end_key = (int(max_end["Year"]), int(max_end["Month"]), int(max_end["Day"]))
    keys = list(zip(min_df["Year"].astype(int), min_df["Month"].astype(int), min_df["Day"].astype(int)))
    keep = [key <= end_key for key in keys]
    trimmed = min_df.loc[keep].copy()
    trimmed.to_csv(min_path, index=False, encoding="utf-8-sig")
    print(f"min trimmed to max end date {end_key}: rows={len(min_df)} -> {len(trimmed)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 2015-2026 max/min temperature CSVs.")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--temp-root", type=Path, default=TEMP_ROOT)
    args = parser.parse_args()
    build("max", args.years, args.temp_root)
    build("min", args.years, args.temp_root)
    trim_min_to_max_end(args.temp_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
