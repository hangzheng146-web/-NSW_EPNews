#!/usr/bin/env python3
"""Build a first-pass 5-minute NSW trading dataset from local price, weather, and news CSVs."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICE_ROOT = ROOT / "CollectedData" / "Electricity prices from NEM" / "original_price_data"
DEFAULT_TEMP_ROOT = ROOT / "CollectedData" / "Temperature" / "temperature"
DEFAULT_NEWS_DIR = ROOT / "CollectedData" / "Classified news"
DEFAULT_OUTPUT = ROOT / "DATASET for experiment" / "TRADING" / "nsw_trading_5min_2025_2026.csv"


def parse_level(text: str) -> int | None:
    match = re.search(r"Level\s*([123])", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def read_prices(price_root: Path, years: list[int]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for year in years:
        folder = price_root / str(year) / "NSW"
        for path in sorted(folder.glob("PRICE_AND_DEMAND_*_NSW1.csv")):
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("REGION") != "NSW1":
                        continue
                    rows.append(
                        {
                            "SETTLEMENTDATE": row["SETTLEMENTDATE"],
                            "REGION": row["REGION"],
                            "TOTALDEMAND": row["TOTALDEMAND"],
                            "RRP": row["RRP"],
                            "PERIODTYPE": row.get("PERIODTYPE", ""),
                        }
                    )
    rows.sort(key=lambda r: r["SETTLEMENTDATE"])
    return rows


def read_temperature(temp_root: Path, kind: str, years: list[int]) -> dict[str, float]:
    if kind == "max":
        pattern = "IDCJAC0010_*_Data.csv"
        value_col = "Maximum temperature (Degree C)"
    else:
        pattern = "IDCJAC0011_*_Data.csv"
        value_col = "Minimum temperature (Degree C)"

    by_date: dict[str, list[float]] = defaultdict(list)
    for path in sorted((temp_root / kind).glob(f"*/{pattern}")):
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    year = int(row["Year"])
                except (KeyError, ValueError):
                    continue
                if year not in years:
                    continue
                value = row.get(value_col, "")
                if value == "":
                    continue
                try:
                    date = f"{int(row['Year']):04d}-{int(row['Month']):02d}-{int(row['Day']):02d}"
                    by_date[date].append(float(value))
                except ValueError:
                    continue
    return {date: sum(values) / len(values) for date, values in by_date.items() if values}


def read_news_features(news_dir: Path, years: list[int]) -> dict[str, dict[str, int]]:
    by_date: dict[str, Counter[str]] = defaultdict(Counter)
    for year in years:
        for suffix in ("news_level1_2", "news"):
            path = news_dir / f"{year}_{suffix}.csv"
            if path.exists():
                break
        else:
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    dt = datetime.strptime(row["date"], "%d-%m-%Y %I:%M:%S %p")
                except (KeyError, ValueError):
                    continue
                date = dt.strftime("%Y-%m-%d")
                by_date[date]["news_count"] += 1
                level = parse_level(row.get("classified_content", ""))
                if level is None:
                    by_date[date]["news_unknown"] += 1
                else:
                    by_date[date][f"news_level_{level}"] += 1
    return {date: dict(counter) for date, counter in by_date.items()}


def price_date(value: str) -> str:
    return datetime.strptime(value, "%Y/%m/%d %H:%M:%S").strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a first-pass NSW trading dataset.")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    parser.add_argument("--price-root", type=Path, default=DEFAULT_PRICE_ROOT)
    parser.add_argument("--temp-root", type=Path, default=DEFAULT_TEMP_ROOT)
    parser.add_argument("--news-dir", type=Path, default=DEFAULT_NEWS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--drop-missing-temp",
        action="store_true",
        help="Drop price intervals whose daily max/min temperature is unavailable.",
    )
    args = parser.parse_args()

    prices = read_prices(args.price_root, args.years)
    max_temp = read_temperature(args.temp_root, "max", args.years)
    min_temp = read_temperature(args.temp_root, "min", args.years)
    news = read_news_features(args.news_dir, args.years)

    fieldnames = [
        "SETTLEMENTDATE",
        "date",
        "REGION",
        "TOTALDEMAND",
        "RRP",
        "PERIODTYPE",
        "max_temp",
        "min_temp",
        "news_count",
        "news_level_1",
        "news_level_2",
        "news_level_3",
        "news_unknown",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    missing_temp = Counter()
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in prices:
            date = price_date(row["SETTLEMENTDATE"])
            if date not in max_temp:
                missing_temp["max_temp"] += 1
            if date not in min_temp:
                missing_temp["min_temp"] += 1
            if args.drop_missing_temp and (date not in max_temp or date not in min_temp):
                continue
            news_features = news.get(date, {})
            writer.writerow(
                {
                    **row,
                    "date": date,
                    "max_temp": max_temp.get(date, ""),
                    "min_temp": min_temp.get(date, ""),
                    "news_count": news_features.get("news_count", 0),
                    "news_level_1": news_features.get("news_level_1", 0),
                    "news_level_2": news_features.get("news_level_2", 0),
                    "news_level_3": news_features.get("news_level_3", 0),
                    "news_unknown": news_features.get("news_unknown", 0),
                }
            )

    unique_dates = {price_date(row["SETTLEMENTDATE"]) for row in prices}
    print(f"prices={len(prices)} dates={len(unique_dates)} output={args.output}")
    print(f"temp_dates=max:{len(max_temp)} min:{len(min_temp)} news_dates={len(news)}")
    print(f"missing_temp_intervals={dict(missing_temp)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
