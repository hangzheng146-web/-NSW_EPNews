#!/usr/bin/env python3
"""Train/evaluate a persistence baseline for 7-day NSW half-hour RRP forecasting.

Persistence has no learned numeric weights. The saved model artifact records the
strategy and split metadata so the exact baseline can be reproduced.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "dataset_hist28_pred7.npz"
DEFAULT_METADATA = HERE / "dataset_hist28_pred7_metadata.csv"
DEFAULT_ARTIFACT = HERE / "models" / "persistence_baseline_model.json"
DEFAULT_PREDICTIONS = HERE / "predictions" / "persistence_baseline_predictions_test.npz"
DEFAULT_REPORT = HERE / "reports" / "persistence_baseline_report.md"


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = np.abs(y_true) > 1e-6
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.abs(y_true) + np.abs(y_pred)
    mask = denom > 1e-6
    return float(np.mean(2 * np.abs(y_pred[mask] - y_true[mask]) / denom[mask]) * 100)


def persistence_predict(x_price_history: np.ndarray, pred_days: int) -> np.ndarray:
    """Use the latest pred_days from history as the next pred_days forecast."""
    return x_price_history[:, -pred_days:, :]


def metric_table_by_day(y_true: np.ndarray, y_pred: np.ndarray) -> pd.DataFrame:
    rows = []
    for day_idx in range(y_true.shape[1]):
        yt = y_true[:, day_idx, :]
        yp = y_pred[:, day_idx, :]
        rows.append(
            {
                "forecast_day": day_idx + 1,
                "MAE": mae(yt, yp),
                "RMSE": rmse(yt, yp),
                "MAPE_%": mape(yt, yp),
                "sMAPE_%": smape(yt, yp),
            }
        )
    return pd.DataFrame(rows)


def format_markdown_table(df: pd.DataFrame) -> str:
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---:" if col != "forecast_day" else "---:" for col in headers]) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in headers:
            if col == "forecast_day":
                values.append(str(int(row[col])))
            else:
                values.append(f"{float(row[col]):.4f}")
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate persistence baseline for NSW 7-day RRP forecasting.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    data = np.load(args.dataset)
    x_price = data["X_price_history"]
    x_temp_hist = data["X_temp_history"]
    x_future = data["X_future_features"]
    y = data["y"]
    metadata = pd.read_csv(args.metadata)

    split_idx = int(len(y) * args.train_ratio)
    if split_idx <= 0 or split_idx >= len(y):
        raise ValueError("train-ratio must leave non-empty train and test splits")

    y_test = y[split_idx:]
    x_price_test = x_price[split_idx:]
    y_pred = persistence_predict(x_price_test, pred_days=y.shape[1])

    overall = {
        "MAE": mae(y_test, y_pred),
        "RMSE": rmse(y_test, y_pred),
        "MAPE_%": mape(y_test, y_pred),
        "sMAPE_%": smape(y_test, y_pred),
    }
    by_day = metric_table_by_day(y_test, y_pred)

    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "model_name": "persistence_baseline",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "strategy": "predict future 7 days by copying the most recent 7 historical days",
        "dataset": str(args.dataset),
        "metadata": str(args.metadata),
        "train_ratio": args.train_ratio,
        "split_idx": split_idx,
        "train_samples": split_idx,
        "test_samples": len(y) - split_idx,
        "input_shapes": {
            "X_price_history": list(x_price.shape),
            "X_temp_history": list(x_temp_hist.shape),
            "X_future_features": list(x_future.shape),
            "y": list(y.shape),
        },
        "uses_features": {
            "historical_half_hour_prices": True,
            "historical_max_min_avg_temperature": False,
            "future_max_min_avg_temperature": False,
            "calendar_features": False,
        },
        "note": "Persistence baseline has no learned numeric weights; this JSON is the reproducible model artifact.",
        "overall_metrics": overall,
    }
    args.artifact.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.predictions,
        y_true=y_test,
        y_pred=y_pred,
        test_metadata=metadata.iloc[split_idx:].to_numpy(dtype=str),
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    test_meta = metadata.iloc[split_idx:]
    report = f"""# Persistence Baseline Report

## Task

Predict future 7 days of NSW half-hourly RRP:

```text
output shape per sample = 7 days * 48 half-hour prices = 336 values
```

## Data

- Dataset: `{args.dataset.name}`
- Source variables available in dataset:
  - historical half-hour prices
  - historical daily max/min average temperature
  - future daily max/min average temperature
  - future calendar features
- Baseline actually used: historical price only.

Persistence is intentionally simple: it copies the latest 7 historical days of price curves as the forecast for the next 7 days. It is not expected to use temperature, but it provides the minimum benchmark that later temperature-aware models should beat.

## Split

Chronological split:

| Split | Samples | Range |
|---|---:|---|
| Train | {split_idx} | {metadata.iloc[0]['sample_date']} to {metadata.iloc[split_idx - 1]['sample_date']} |
| Test | {len(y) - split_idx} | {test_meta.iloc[0]['sample_date']} to {test_meta.iloc[-1]['sample_date']} |

## Overall Test Metrics

| Metric | Value |
|---|---:|
| MAE | {overall['MAE']:.4f} |
| RMSE | {overall['RMSE']:.4f} |
| MAPE % | {overall['MAPE_%']:.4f} |
| sMAPE % | {overall['sMAPE_%']:.4f} |

## Metrics By Forecast Day

{format_markdown_table(by_day)}

## Saved Artifacts

- Model artifact: `{args.artifact}`
- Test predictions: `{args.predictions}`

## Interpretation

This baseline measures weekly price-pattern persistence. If later models using temperature and richer history cannot beat this MAE/RMSE on the same chronological test split, they are not adding useful predictive signal.

The model has no trainable weights. The saved JSON artifact records the exact persistence rule, input shapes, split index, and evaluation metrics so the baseline is reproducible.
"""
    args.report.write_text(report, encoding="utf-8")

    print(json.dumps({"overall": overall, "artifact": str(args.artifact), "report": str(args.report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
