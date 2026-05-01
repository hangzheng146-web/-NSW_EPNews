#!/usr/bin/env python3
"""Create daily supervised samples for NSW battery trading research.

Each sample uses rolling historical daily features and predicts future daily
price/arbitrage targets. This is intentionally compact enough for quick
baseline modeling before moving to sequence models.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "DATASET for experiment" / "TRADING" / "nsw_trading_5min_2025_2026.csv"
DEFAULT_OUTPUT = ROOT / "DATASET for experiment" / "TRADING" / "nsw_supervised_daily_hist60_pred7.csv"


def safe_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    pos = (len(sorted_values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def daily_metrics(rows: list[dict[str, str]]) -> dict[str, float]:
    rrps = [safe_float(row["RRP"]) for row in rows]
    rrps = [value for value in rrps if value is not None]
    demands = [safe_float(row["TOTALDEMAND"]) for row in rows]
    demands = [value for value in demands if value is not None]
    max_temps = [safe_float(row["max_temp"]) for row in rows]
    min_temps = [safe_float(row["min_temp"]) for row in rows]
    news_count = max(int(float(row["news_count"])) for row in rows) if rows else 0
    news_level_1 = max(int(float(row["news_level_1"])) for row in rows) if rows else 0
    news_level_2 = max(int(float(row["news_level_2"])) for row in rows) if rows else 0
    news_level_3 = max(int(float(row["news_level_3"])) for row in rows) if rows else 0

    return {
        "intervals": float(len(rows)),
        "rrp_mean": mean(rrps) if rrps else 0.0,
        "rrp_min": min(rrps) if rrps else 0.0,
        "rrp_max": max(rrps) if rrps else 0.0,
        "rrp_p10": percentile(rrps, 0.10),
        "rrp_p50": percentile(rrps, 0.50),
        "rrp_p90": percentile(rrps, 0.90),
        "rrp_spread_p90_p10": percentile(rrps, 0.90) - percentile(rrps, 0.10),
        "rrp_negative_intervals": float(sum(1 for value in rrps if value < 0)),
        "rrp_high_300_intervals": float(sum(1 for value in rrps if value >= 300)),
        "rrp_high_1000_intervals": float(sum(1 for value in rrps if value >= 1000)),
        "demand_mean": mean(demands) if demands else 0.0,
        "demand_max": max(demands) if demands else 0.0,
        "max_temp": mean([v for v in max_temps if v is not None]) if any(v is not None for v in max_temps) else 0.0,
        "min_temp": mean([v for v in min_temps if v is not None]) if any(v is not None for v in min_temps) else 0.0,
        "news_count": float(news_count),
        "news_level_1": float(news_level_1),
        "news_level_2": float(news_level_2),
        "news_level_3": float(news_level_3),
    }


def average_metric(days: list[dict[str, float]], key: str) -> float:
    return mean(day[key] for day in days) if days else 0.0


def max_metric(days: list[dict[str, float]], key: str) -> float:
    return max((day[key] for day in days), default=0.0)


def sum_metric(days: list[dict[str, float]], key: str) -> float:
    return sum(day[key] for day in days)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact supervised daily trading samples.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--hist-days", type=int, default=60)
    parser.add_argument("--pred-days", type=int, default=7)
    args = parser.parse_args()

    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    with args.input.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            by_date[row["date"]].append(row)

    dates = sorted(by_date)
    day_metrics = {date: daily_metrics(by_date[date]) for date in dates}

    fieldnames = [
        "sample_date",
        "prediction_start_date",
        "prediction_end_date",
        "hist_days",
        "pred_days",
        "hist_rrp_mean_60d",
        "hist_rrp_max_60d",
        "hist_rrp_min_60d",
        "hist_rrp_spread_mean_60d",
        "hist_negative_intervals_60d",
        "hist_high_300_intervals_60d",
        "hist_high_1000_intervals_60d",
        "hist_demand_mean_60d",
        "hist_demand_max_60d",
        "hist_max_temp_mean_60d",
        "hist_min_temp_mean_60d",
        "hist_news_count_60d",
        "hist_news_level_1_60d",
        "hist_news_level_2_60d",
        "target_rrp_mean_7d",
        "target_rrp_max_7d",
        "target_rrp_min_7d",
        "target_rrp_spread_mean_7d",
        "target_negative_intervals_7d",
        "target_high_300_intervals_7d",
        "target_high_1000_intervals_7d",
        "target_arbitrage_spread_p90_p10_7d",
        "target_best_daily_spread_7d",
    ]

    samples: list[dict[str, str | int | float]] = []
    for index in range(args.hist_days, len(dates) - args.pred_days + 1):
        hist_dates = dates[index - args.hist_days : index]
        pred_dates = dates[index : index + args.pred_days]
        hist = [day_metrics[date] for date in hist_dates]
        pred = [day_metrics[date] for date in pred_dates]
        samples.append(
            {
                "sample_date": hist_dates[-1],
                "prediction_start_date": pred_dates[0],
                "prediction_end_date": pred_dates[-1],
                "hist_days": args.hist_days,
                "pred_days": args.pred_days,
                "hist_rrp_mean_60d": average_metric(hist, "rrp_mean"),
                "hist_rrp_max_60d": max_metric(hist, "rrp_max"),
                "hist_rrp_min_60d": min(day["rrp_min"] for day in hist),
                "hist_rrp_spread_mean_60d": average_metric(hist, "rrp_spread_p90_p10"),
                "hist_negative_intervals_60d": sum_metric(hist, "rrp_negative_intervals"),
                "hist_high_300_intervals_60d": sum_metric(hist, "rrp_high_300_intervals"),
                "hist_high_1000_intervals_60d": sum_metric(hist, "rrp_high_1000_intervals"),
                "hist_demand_mean_60d": average_metric(hist, "demand_mean"),
                "hist_demand_max_60d": max_metric(hist, "demand_max"),
                "hist_max_temp_mean_60d": average_metric(hist, "max_temp"),
                "hist_min_temp_mean_60d": average_metric(hist, "min_temp"),
                "hist_news_count_60d": sum_metric(hist, "news_count"),
                "hist_news_level_1_60d": sum_metric(hist, "news_level_1"),
                "hist_news_level_2_60d": sum_metric(hist, "news_level_2"),
                "target_rrp_mean_7d": average_metric(pred, "rrp_mean"),
                "target_rrp_max_7d": max_metric(pred, "rrp_max"),
                "target_rrp_min_7d": min(day["rrp_min"] for day in pred),
                "target_rrp_spread_mean_7d": average_metric(pred, "rrp_spread_p90_p10"),
                "target_negative_intervals_7d": sum_metric(pred, "rrp_negative_intervals"),
                "target_high_300_intervals_7d": sum_metric(pred, "rrp_high_300_intervals"),
                "target_high_1000_intervals_7d": sum_metric(pred, "rrp_high_1000_intervals"),
                "target_arbitrage_spread_p90_p10_7d": average_metric(pred, "rrp_spread_p90_p10"),
                "target_best_daily_spread_7d": max_metric(pred, "rrp_spread_p90_p10"),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)

    print(f"input_days={len(dates)} samples={len(samples)} output={args.output}")
    if samples:
        print(f"first_sample={samples[0]['sample_date']} -> {samples[0]['prediction_start_date']}..{samples[0]['prediction_end_date']}")
        print(f"last_sample={samples[-1]['sample_date']} -> {samples[-1]['prediction_start_date']}..{samples[-1]['prediction_end_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
