#!/usr/bin/env python3
"""Train rolling slot-wise ARIMA baselines for 7-day half-hour RRP forecasting."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from statsmodels.tsa.arima.model import ARIMA


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "dataset_hist28_pred7.npz"
DEFAULT_METADATA = HERE / "dataset_hist28_pred7_metadata.csv"
DEFAULT_OUTPUT = HERE / "predictions" / "arima_predictions_test.npz"
DEFAULT_SUMMARY = HERE / "models" / "arima_baseline_summary.json"
DEFAULT_MODEL = HERE / "models" / "arima_slotwise_48models.joblib"


def metric_dict(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = y_true - y_pred
    mask = np.abs(y_true) > 1e-6
    denom = np.abs(y_true) + np.abs(y_pred)
    smape_mask = denom > 1e-6
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAPE_%": float(np.mean(np.abs(err[mask] / y_true[mask])) * 100),
        "sMAPE_%": float(np.mean(2 * np.abs(err[smape_mask]) / denom[smape_mask]) * 100),
    }


def metrics_by_day(y_true: np.ndarray, y_pred: np.ndarray) -> list[dict[str, float]]:
    rows = []
    for i in range(y_true.shape[1]):
        rows.append({"forecast_day": i + 1, **metric_dict(y_true[:, i, :], y_pred[:, i, :])})
    return rows


def build_daily_price_matrix(dataset: np.lib.npyio.NpzFile, metadata: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    x_price = dataset["X_price_history"]
    y = dataset["y"]
    seen = {}

    first_history_end = pd.Timestamp(metadata.iloc[0]["sample_date"])
    hist_days = x_price.shape[1]
    hist_dates = pd.date_range(first_history_end - pd.Timedelta(days=hist_days - 1), periods=hist_days, freq="D")
    for idx, date in enumerate(hist_dates):
        seen[str(date.date())] = x_price[0, idx, :]

    for idx, row in metadata.iterrows():
        pred_dates = pd.date_range(row["prediction_start_date"], row["prediction_end_date"], freq="D")
        for day_idx, date in enumerate(pred_dates):
            seen.setdefault(str(date.date()), y[idx, day_idx, :])

    ordered_dates = sorted(seen)
    matrix = np.stack([seen[date] for date in ordered_dates]).astype(np.float32)
    return matrix, ordered_dates


def fit_slot_arima(train_series: np.ndarray, order: tuple[int, int, int]) -> object:
    try:
        model = ARIMA(train_series, order=order, enforce_stationarity=False, enforce_invertibility=False)
        return model.fit(method_kwargs={"warn_convergence": False})
    except Exception:
        return None


def date_key(value: object) -> str:
    return str(pd.Timestamp(value).date())


def main() -> int:
    parser = argparse.ArgumentParser(description="Train/evaluate ARIMA baseline.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--order", default="1,0,1", help="ARIMA order p,d,q")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--model-output", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    p, d, q = [int(x) for x in args.order.split(",")]
    order = (p, d, q)
    dataset = np.load(args.dataset)
    metadata = pd.read_csv(args.metadata)
    x_price = dataset["X_price_history"]
    y = dataset["y"]
    split = int(len(y) * args.train_ratio)
    y_test = y[split:]
    test_meta = metadata.iloc[split:].reset_index(drop=True)
    price_matrix, dates = build_daily_price_matrix(dataset, metadata)
    date_to_idx = {date: idx for idx, date in enumerate(dates)}

    fitted = []
    last_train_date = date_key(metadata.iloc[split - 1]["sample_date"])
    train_end_idx = date_to_idx[last_train_date]
    for slot in range(48):
        fitted.append(fit_slot_arima(price_matrix[: train_end_idx + 1, slot], order=order))
    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": fitted, "order": order, "slots": 48}, args.model_output)

    preds = np.zeros_like(y_test, dtype=np.float32)
    fallback_count = 0
    for sample_idx, row in test_meta.iterrows():
        for slot in range(48):
            result = fitted[slot]
            if result is None:
                fallback_count += 1
                preds[sample_idx, :, slot] = x_price[split + sample_idx, -7:, slot]
                continue
            try:
                steps = date_to_idx[date_key(row["prediction_end_date"])] - train_end_idx
                forecast_from_train = result.forecast(steps=steps)
                start_offset = date_to_idx[date_key(row["prediction_start_date"])] - train_end_idx - 1
                preds[sample_idx, :, slot] = forecast_from_train[start_offset : start_offset + 7]
            except Exception:
                fallback_count += 1
                preds[sample_idx, :, slot] = x_price[split + sample_idx, -7:, slot]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, y_true=y_test, y_pred=preds)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model_name": "slotwise_arima",
        "order": order,
        "strategy": "Fit one ARIMA model per half-hour slot on chronological training data; forecast slot-wise future daily values.",
        "train_samples": split,
        "test_samples": len(y) - split,
        "metrics": metric_dict(y_test, preds),
        "metrics_by_day": metrics_by_day(y_test, preds),
        "fallback_count": fallback_count,
        "prediction_file": str(args.output),
        "model_file": str(args.model_output),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
