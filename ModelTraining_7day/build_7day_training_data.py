#!/usr/bin/env python3
"""Build supervised arrays for 7-day NSW half-hour RRP forecasting."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICE = ROOT / "CollectedData" / "Electricity prices from NEM" / "unified_price_data" / "unified_used_for_experiment" / "2015To2026Data.csv"
DEFAULT_MAX_TEMP = ROOT / "CollectedData" / "Temperature" / "max_temps_2015_2026.csv"
DEFAULT_MIN_TEMP = ROOT / "CollectedData" / "Temperature" / "min_temps_2015_2026.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "dataset_hist28_pred7.npz"
DEFAULT_META = Path(__file__).resolve().parent / "dataset_hist28_pred7_metadata.csv"


def read_prices(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["REGION"] == "NSW1"].copy()
    df["dt"] = pd.to_datetime(df["SETTLEMENTDATE"], dayfirst=True, errors="raise")
    df["date"] = df["dt"].dt.date
    df["time"] = df["dt"].dt.strftime("%H:%M")
    df["RRP"] = pd.to_numeric(df["RRP"], errors="raise")
    return df.sort_values("dt")


def daily_price_matrix(df: pd.DataFrame) -> pd.DataFrame:
    pivot = df.pivot_table(index="date", columns="time", values="RRP", aggfunc="last")
    expected_times = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]
    pivot = pivot.reindex(columns=expected_times)
    complete = pivot.notna().sum(axis=1) == 48
    dropped = int((~complete).sum())
    if dropped:
        print(f"dropping incomplete price days={dropped}")
    return pivot.loc[complete].sort_index()


def read_temperature(max_path: Path, min_path: Path) -> pd.DataFrame:
    max_df = pd.read_csv(max_path)
    min_df = pd.read_csv(min_path)
    max_df["date"] = pd.to_datetime(max_df[["Year", "Month", "Day"]]).dt.date
    min_df["date"] = pd.to_datetime(min_df[["Year", "Month", "Day"]]).dt.date
    max_daily = (
        max_df.groupby("date")["Maximum temperature (Degree C)"]
        .mean()
        .rename("max_temp")
    )
    min_daily = (
        min_df.groupby("date")["Minimum temperature (Degree C)"]
        .mean()
        .rename("min_temp")
    )
    return pd.concat([max_daily, min_daily], axis=1).dropna().sort_index()


def calendar_features(dates: list[object]) -> np.ndarray:
    rows = []
    for date in dates:
        ts = pd.Timestamp(date)
        dow = ts.dayofweek
        month = ts.month
        rows.append(
            [
                math.sin(2 * math.pi * dow / 7),
                math.cos(2 * math.pi * dow / 7),
                math.sin(2 * math.pi * month / 12),
                math.cos(2 * math.pi * month / 12),
            ]
        )
    return np.asarray(rows, dtype=np.float32)


def build_samples(price_daily: pd.DataFrame, temp_daily: pd.DataFrame, hist_days: int, pred_days: int):
    common_dates = sorted(set(price_daily.index).intersection(set(temp_daily.index)))
    price_daily = price_daily.loc[common_dates]
    temp_daily = temp_daily.loc[common_dates]

    x_price = []
    x_temp_hist = []
    x_future = []
    y = []
    metadata = []

    for i in range(hist_days, len(common_dates) - pred_days + 1):
        hist_dates = common_dates[i - hist_days : i]
        pred_dates = common_dates[i : i + pred_days]
        # Require contiguous calendar days. This avoids hidden gaps around partial downloads.
        all_dates = hist_dates + pred_dates
        expected = pd.date_range(all_dates[0], periods=len(all_dates), freq="D").date.tolist()
        if list(all_dates) != expected:
            continue

        hist_price = price_daily.loc[hist_dates].to_numpy(dtype=np.float32)
        hist_temp = temp_daily.loc[hist_dates, ["max_temp", "min_temp"]].to_numpy(dtype=np.float32)
        future_temp = temp_daily.loc[pred_dates, ["max_temp", "min_temp"]].to_numpy(dtype=np.float32)
        future_cal = calendar_features(pred_dates)
        target = price_daily.loc[pred_dates].to_numpy(dtype=np.float32)

        x_price.append(hist_price)
        x_temp_hist.append(hist_temp)
        x_future.append(np.concatenate([future_temp, future_cal], axis=1))
        y.append(target)
        metadata.append(
            {
                "sample_date": str(hist_dates[-1]),
                "prediction_start_date": str(pred_dates[0]),
                "prediction_end_date": str(pred_dates[-1]),
            }
        )

    return (
        np.asarray(x_price, dtype=np.float32),
        np.asarray(x_temp_hist, dtype=np.float32),
        np.asarray(x_future, dtype=np.float32),
        np.asarray(y, dtype=np.float32),
        metadata,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 7-day NSW half-hour price forecasting arrays.")
    parser.add_argument("--price", type=Path, default=DEFAULT_PRICE)
    parser.add_argument("--max-temp", type=Path, default=DEFAULT_MAX_TEMP)
    parser.add_argument("--min-temp", type=Path, default=DEFAULT_MIN_TEMP)
    parser.add_argument("--hist-days", type=int, default=28)
    parser.add_argument("--pred-days", type=int, default=7)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_META)
    args = parser.parse_args()

    prices = read_prices(args.price)
    price_daily = daily_price_matrix(prices)
    temp_daily = read_temperature(args.max_temp, args.min_temp)
    x_price, x_temp_hist, x_future, y, metadata = build_samples(
        price_daily=price_daily,
        temp_daily=temp_daily,
        hist_days=args.hist_days,
        pred_days=args.pred_days,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        X_price_history=x_price,
        X_temp_history=x_temp_hist,
        X_future_features=x_future,
        y=y,
    )
    pd.DataFrame(metadata).to_csv(args.metadata, index=False)

    summary = {
        "samples": int(y.shape[0]),
        "X_price_history": list(x_price.shape),
        "X_temp_history": list(x_temp_hist.shape),
        "X_future_features": list(x_future.shape),
        "y": list(y.shape),
        "first_sample": metadata[0] if metadata else None,
        "last_sample": metadata[-1] if metadata else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
