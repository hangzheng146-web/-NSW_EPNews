#!/usr/bin/env python3
"""Audit local NSW-EPNews collected data for 2025/2026 extension work."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRICE_ROOT = ROOT / "CollectedData" / "Electricity prices from NEM" / "original_price_data"
TEMP_ROOT = ROOT / "CollectedData" / "Temperature" / "temperature"
NEWS_DIR = ROOT / "CollectedData" / "Classified news"


def parse_level(text: str) -> str:
    match = re.search(r"Level\s*([123])", text or "", flags=re.IGNORECASE)
    return f"Level {match.group(1)}" if match else "Unknown"


def audit_prices(years: list[int]) -> None:
    print("== PRICE ==")
    for year in years:
        folder = PRICE_ROOT / str(year) / "NSW"
        files = sorted(folder.glob("PRICE_AND_DEMAND_*_NSW1.csv"))
        print(f"{year}: files={len(files)} folder={folder}")
        for path in files:
            rows = 0
            dates: list[datetime] = []
            regions = Counter()
            headers = None
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                for row in reader:
                    rows += 1
                    regions[row.get("REGION", "")] += 1
                    try:
                        dates.append(datetime.strptime(row["SETTLEMENTDATE"], "%Y/%m/%d %H:%M:%S"))
                    except Exception:
                        pass
            expected = "OK" if headers == ["REGION", "SETTLEMENTDATE", "TOTALDEMAND", "RRP", "PERIODTYPE"] else "BAD_HEADER"
            start = min(dates).strftime("%Y-%m-%d %H:%M") if dates else "NA"
            end = max(dates).strftime("%Y-%m-%d %H:%M") if dates else "NA"
            print(f"  {path.name}: rows={rows} range={start}..{end} regions={dict(regions)} {expected}")


def audit_temperature(years: list[int]) -> None:
    print("== TEMPERATURE ==")
    for kind, product, value_col in [
        ("max", "IDCJAC0010", "Maximum temperature (Degree C)"),
        ("min", "IDCJAC0011", "Minimum temperature (Degree C)"),
    ]:
        print(f"-- {kind} --")
        for year in years:
            paths = sorted((TEMP_ROOT / kind).glob(f"{product}_*_{year}/{product}_*_{year}_Data.csv"))
            print(f"{kind} {year}: files={len(paths)}")
            for path in paths:
                dates = []
                stations = Counter()
                missing_values = 0
                headers = None
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames
                    for row in reader:
                        stations[row.get("Bureau of Meteorology station number", "")] += 1
                        if row.get(value_col, "") == "":
                            missing_values += 1
                        try:
                            dates.append(datetime(int(row["Year"]), int(row["Month"]), int(row["Day"])))
                        except Exception:
                            pass
                start = min(dates).strftime("%Y-%m-%d") if dates else "NA"
                end = max(dates).strftime("%Y-%m-%d") if dates else "NA"
                header_status = "OK" if headers and value_col in headers else "BAD_HEADER"
                print(f"  {path}: rows={len(dates)} range={start}..{end} stations={dict(stations)} missing={missing_values} {header_status}")


def audit_news(years: list[int]) -> None:
    print("== NEWS ==")
    for year in years:
        path = NEWS_DIR / f"{year}_news.csv"
        if not path.exists():
            print(f"{year}: MISSING {path}")
            continue
        rows = []
        dates = []
        levels = Counter()
        titles = Counter()
        bad_dates = 0
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            for row in reader:
                rows.append(row)
                titles[row.get("title", "")] += 1
                levels[parse_level(row.get("classified_content", ""))] += 1
                try:
                    dates.append(datetime.strptime(row["date"], "%d-%m-%Y %I:%M:%S %p"))
                except Exception:
                    bad_dates += 1
        months = Counter(dt.strftime("%Y-%m") for dt in dates)
        duplicates = sum(1 for count in titles.values() if count > 1)
        start = min(dates).strftime("%Y-%m-%d") if dates else "NA"
        end = max(dates).strftime("%Y-%m-%d") if dates else "NA"
        header_status = "OK" if headers == ["title", "author", "date", "topic", "classified_content"] else f"HEADER={headers}"
        print(f"{year}: rows={len(rows)} range={start}..{end} bad_dates={bad_dates} duplicate_titles={duplicates} {header_status}")
        print(f"  levels={dict(levels)}")
        print(f"  months={dict(sorted(months.items()))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit collected NSW-EPNews data.")
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2026])
    args = parser.parse_args()
    audit_prices(args.years)
    audit_temperature(args.years)
    audit_news(args.years)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
