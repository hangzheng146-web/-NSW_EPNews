#!/usr/bin/env python3
"""Run a tiny leakage-safe chronological baseline on supervised trading samples."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "DATASET for experiment" / "TRADING" / "nsw_supervised_daily_hist60_pred7.csv"


def mae(y_true: list[float], y_pred: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)


def rmse(y_true: list[float], y_pred: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / len(y_true))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simple chronological baseline.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--target", default="target_arbitrage_spread_p90_p10_7d")
    parser.add_argument("--feature", default="hist_rrp_spread_mean_60d")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    split = int(len(rows) * args.train_ratio)
    train = rows[:split]
    test = rows[split:]
    if not train or not test:
        raise ValueError("Need both train and test rows.")

    train_mean_target = sum(float(row[args.target]) for row in train) / len(train)

    y_true = [float(row[args.target]) for row in test]
    pred_feature = [float(row[args.feature]) for row in test]
    pred_train_mean = [train_mean_target] * len(test)

    print(f"rows={len(rows)} train={len(train)} test={len(test)}")
    print(f"target={args.target}")
    print(f"baseline_feature={args.feature} mae={mae(y_true, pred_feature):.4f} rmse={rmse(y_true, pred_feature):.4f}")
    print(f"baseline_train_mean mae={mae(y_true, pred_train_mean):.4f} rmse={rmse(y_true, pred_train_mean):.4f}")
    print(f"test_range={test[0]['sample_date']}..{test[-1]['sample_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
