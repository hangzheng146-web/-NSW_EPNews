#!/usr/bin/env python3
"""Train LightGBM/XGBoost long-format models for 7-day half-hour RRP forecasting.

Instead of fitting 336 separate output models, this expands each sample into
7*48 rows and trains one scalar regressor per algorithm. Forecast day and
half-hour slot are included as features, so the model can emit the full
7-day-by-48 forecast grid.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "dataset_hist28_pred7.npz"
DEFAULT_METADATA = HERE / "dataset_hist28_pred7_metadata.csv"
DEFAULT_REPORT = HERE / "reports" / "gbdt_long_models_report.md"


def build_long_features(x_price: np.ndarray, x_temp_hist: np.ndarray, x_future: np.ndarray, y: np.ndarray):
    n, hist_days, periods = x_price.shape
    pred_days = y.shape[1]
    rows = n * pred_days * periods

    feature_names = []
    features = []

    # Row index grids.
    sample_idx = np.repeat(np.arange(n), pred_days * periods)
    day_idx = np.tile(np.repeat(np.arange(pred_days), periods), n)
    slot_idx = np.tile(np.arange(periods), n * pred_days)

    # Recent same-slot prices from the latest 7 historical days.
    recent = x_price[:, -7:, :]  # [n, 7, 48]
    for lag in range(7):
        feature_names.append(f"same_slot_price_lag_day_{7 - lag}")
        features.append(recent[sample_idx, lag, slot_idx])

    # Same-slot historical statistics over 28 days.
    feature_names.extend(["same_slot_hist_mean", "same_slot_hist_std", "same_slot_hist_min", "same_slot_hist_max"])
    features.extend(
        [
            x_price.mean(axis=1)[sample_idx, slot_idx],
            x_price.std(axis=1)[sample_idx, slot_idx],
            x_price.min(axis=1)[sample_idx, slot_idx],
            x_price.max(axis=1)[sample_idx, slot_idx],
        ]
    )

    # Whole-day recent price statistics.
    last_day = x_price[:, -1, :]
    feature_names.extend(["last_day_mean", "last_day_min", "last_day_max", "last_day_std"])
    features.extend(
        [
            last_day.mean(axis=1)[sample_idx],
            last_day.min(axis=1)[sample_idx],
            last_day.max(axis=1)[sample_idx],
            last_day.std(axis=1)[sample_idx],
        ]
    )

    # Historical temperature summary: max, min, avg.
    hist_max = x_temp_hist[:, :, 0]
    hist_min = x_temp_hist[:, :, 1]
    hist_avg = (hist_max + hist_min) / 2
    for name, arr in [("hist_max_temp", hist_max), ("hist_min_temp", hist_min), ("hist_avg_temp", hist_avg)]:
        feature_names.extend([f"{name}_mean_28d", f"{name}_last"])
        features.extend([arr.mean(axis=1)[sample_idx], arr[:, -1][sample_idx]])

    # Future temperature for the target forecast day: max, min, avg.
    future_max = x_future[:, :, 0]
    future_min = x_future[:, :, 1]
    future_avg = (future_max + future_min) / 2
    feature_names.extend(["future_max_temp", "future_min_temp", "future_avg_temp"])
    features.extend(
        [
            future_max[sample_idx, day_idx],
            future_min[sample_idx, day_idx],
            future_avg[sample_idx, day_idx],
        ]
    )

    # Horizon and slot encodings.
    slot_angle = 2 * math.pi * slot_idx / periods
    day_angle = 2 * math.pi * day_idx / pred_days
    feature_names.extend(["forecast_day", "slot", "slot_sin", "slot_cos", "forecast_day_sin", "forecast_day_cos"])
    features.extend(
        [
            day_idx + 1,
            slot_idx,
            np.sin(slot_angle),
            np.cos(slot_angle),
            np.sin(day_angle),
            np.cos(day_angle),
        ]
    )

    x_long = np.column_stack(features).astype(np.float32)
    y_long = y.reshape(rows).astype(np.float32)
    index = np.column_stack([sample_idx, day_idx, slot_idx]).astype(np.int32)
    return x_long, y_long, index, feature_names


def predict_grid(model, x_long: np.ndarray, n_samples: int, pred_days: int = 7, periods: int = 48) -> np.ndarray:
    return model.predict(x_long).astype(np.float32).reshape(n_samples, pred_days, periods)


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


def metrics_by_day(y_true: np.ndarray, y_pred: np.ndarray) -> pd.DataFrame:
    rows = []
    for i in range(y_true.shape[1]):
        rows.append({"forecast_day": i + 1, **metric_dict(y_true[:, i, :], y_pred[:, i, :])})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---:" for _ in cols]) + " |"]
    for _, row in df.iterrows():
        vals = []
        for col in cols:
            vals.append(str(row[col]) if isinstance(row[col], str) else (str(int(row[col])) if col == "forecast_day" else f"{float(row[col]):.4f}"))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def persistence_prediction(x_price: np.ndarray, pred_days: int) -> np.ndarray:
    return x_price[:, -pred_days:, :]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train long-format GBDT models.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--models-dir", type=Path, default=HERE / "models")
    parser.add_argument("--predictions-dir", type=Path, default=HERE / "predictions")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lgbm-estimators", type=int, default=200)
    parser.add_argument("--xgb-estimators", type=int, default=200)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--n-jobs", type=int, default=4)
    args = parser.parse_args()

    data = np.load(args.dataset)
    x_price = data["X_price_history"]
    x_temp_hist = data["X_temp_history"]
    x_future = data["X_future_features"]
    y = data["y"]
    metadata = pd.read_csv(args.metadata)

    split = int(len(y) * args.train_ratio)
    x_long, y_long, index, feature_names = build_long_features(x_price, x_temp_hist, x_future, y)
    train_mask = index[:, 0] < split
    test_mask = ~train_mask
    x_train, y_train = x_long[train_mask], y_long[train_mask]
    x_test, y_test_long = x_long[test_mask], y_long[test_mask]
    y_test = y[split:]

    args.models_dir.mkdir(parents=True, exist_ok=True)
    args.predictions_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    print(f"long train rows={len(y_train)} test rows={len(y_test_long)} features={x_train.shape[1]}")

    lgbm = LGBMRegressor(
        objective="regression",
        n_estimators=args.lgbm_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        num_leaves=63,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=args.seed,
        n_jobs=args.n_jobs,
        verbosity=-1,
    )
    print("training LightGBM long model...")
    lgbm.fit(x_train, y_train, feature_name=feature_names)
    lgbm_pred = predict_grid(lgbm, x_test, n_samples=len(y_test))
    lgbm_path = args.models_dir / "lightgbm_long_hist28_pred7.joblib"
    joblib.dump({"model": lgbm, "feature_names": feature_names}, lgbm_path)
    np.savez_compressed(args.predictions_dir / "lightgbm_long_predictions_test.npz", y_true=y_test, y_pred=lgbm_pred)

    xgb = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=args.xgb_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        subsample=0.9,
        colsample_bytree=0.9,
        tree_method="hist",
        random_state=args.seed,
        n_jobs=args.n_jobs,
    )
    print("training XGBoost long model...")
    xgb.fit(x_train, y_train)
    xgb_pred = predict_grid(xgb, x_test, n_samples=len(y_test))
    xgb_path = args.models_dir / "xgboost_long_hist28_pred7.joblib"
    joblib.dump({"model": xgb, "feature_names": feature_names}, xgb_path)
    np.savez_compressed(args.predictions_dir / "xgboost_long_predictions_test.npz", y_true=y_test, y_pred=xgb_pred)

    persistence_pred = persistence_prediction(x_price[split:], pred_days=y.shape[1])
    results = {
        "Persistence": metric_dict(y_test, persistence_pred),
        "LightGBM": metric_dict(y_test, lgbm_pred),
        "XGBoost": metric_dict(y_test, xgb_pred),
    }
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "feature_names": feature_names,
        "train_samples": split,
        "test_samples": len(y) - split,
        "train_rows_long": int(len(y_train)),
        "test_rows_long": int(len(y_test_long)),
        "metrics": results,
        "artifacts": {"LightGBM": str(lgbm_path), "XGBoost": str(xgb_path)},
    }
    summary_path = args.models_dir / "gbdt_long_training_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    overall = pd.DataFrame([{"model": name, **vals} for name, vals in results.items()])
    report_parts = [
        "# LightGBM and XGBoost Long-Format Forecast Report",
        "",
        "## Task",
        "",
        "Predict future 7 days of NSW half-hourly RRP (`7 * 48 = 336` values per sample).",
        "",
        "## Feature Construction",
        "",
        "Each sample is expanded into 336 rows. Each row predicts one forecast-day/half-hour-slot price.",
        "",
        "Features used:",
        "",
        "- Same half-hour slot prices from the latest 7 historical days.",
        "- Same-slot 28-day mean/std/min/max historical price.",
        "- Latest historical day mean/min/max/std price.",
        "- Historical max/min/average temperature summary.",
        "- Future forecast-day max/min/average temperature.",
        "- Forecast day and half-hour slot cyclic encodings.",
        "",
        "During backtesting, future temperature is observed temperature. For real operation, replace it with weather forecast values.",
        "",
        "## Chronological Split",
        "",
        f"- Train samples: `{split}` from `{metadata.iloc[0]['sample_date']}` to `{metadata.iloc[split - 1]['sample_date']}`",
        f"- Test samples: `{len(y) - split}` from `{metadata.iloc[split]['sample_date']}` to `{metadata.iloc[-1]['sample_date']}`",
        f"- Long-format train rows: `{len(y_train)}`",
        f"- Long-format test rows: `{len(y_test_long)}`",
        "",
        "## Overall Test Metrics",
        "",
        markdown_table(overall),
        "",
        "## Metrics By Forecast Day",
        "",
        "### Persistence",
        "",
        markdown_table(metrics_by_day(y_test, persistence_pred)),
        "",
        "### LightGBM",
        "",
        markdown_table(metrics_by_day(y_test, lgbm_pred)),
        "",
        "### XGBoost",
        "",
        markdown_table(metrics_by_day(y_test, xgb_pred)),
        "",
        "## Saved Artifacts",
        "",
        f"- LightGBM weights: `{lgbm_path}`",
        f"- XGBoost weights: `{xgb_path}`",
        f"- Training summary: `{summary_path}`",
        f"- LightGBM predictions: `{args.predictions_dir / 'lightgbm_long_predictions_test.npz'}`",
        f"- XGBoost predictions: `{args.predictions_dir / 'xgboost_long_predictions_test.npz'}`",
        "",
        "## Interpretation Notes",
        "",
        "- Persistence is the benchmark to beat.",
        "- MAPE is unstable for electricity prices because RRP can be close to zero or negative.",
        "- RMSE is strongly affected by price spikes; MAE is often easier to interpret for trading baselines.",
    ]
    args.report.write_text("\n".join(report_parts), encoding="utf-8")
    print(json.dumps({"metrics": results, "report": str(args.report), "artifacts": summary["artifacts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
