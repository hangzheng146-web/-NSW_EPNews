#!/usr/bin/env python3
"""Export one 7-day model forecast into the dashboard JSON contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREDICTIONS = ROOT / "ModelTraining_7day" / "predictions" / "lightgbm_long_predictions_test.npz"
DEFAULT_METADATA = ROOT / "ModelTraining_7day" / "dataset_hist28_pred7_metadata.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "forecast_sample.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export latest LightGBM forecast sample for dashboard.")
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--sample-index", type=int, default=-1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = np.load(args.predictions)
    y_pred = data["y_pred"]
    metadata = pd.read_csv(args.metadata)
    test_offset = len(metadata) - len(y_pred)
    sample_idx = args.sample_index if args.sample_index >= 0 else len(y_pred) + args.sample_index
    meta = metadata.iloc[test_offset + sample_idx]
    start = datetime.strptime(meta["prediction_start_date"], "%Y-%m-%d")

    points = []
    for day in range(y_pred.shape[1]):
        date = start + timedelta(days=day)
        for slot in range(y_pred.shape[2]):
            timestamp = date + timedelta(minutes=30 * slot)
            points.append(
                {
                    "timestamp": timestamp.strftime("%Y-%m-%d %H:%M"),
                    "date": date.strftime("%Y-%m-%d"),
                    "half_hour_index": slot,
                    "predicted_price": round(float(y_pred[sample_idx, day, slot]), 2),
                }
            )

    payload = {
        "metadata": {
            "region": "NSW1",
            "forecast_start": start.strftime("%Y-%m-%d"),
            "forecast_days": 7,
            "frequency": "30min",
            "model_name": "LightGBM-7D-30min",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "thresholds": {
            "low_price_threshold": 30,
            "high_price_threshold": 150,
            "spike_threshold": 300,
        },
        "point_forecast": points,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
