#!/usr/bin/env python3
"""Train LightGBM and XGBoost models for 7-day NSW half-hour RRP forecasting."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.multioutput import MultiOutputRegressor
from xgboost import XGBRegressor


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "dataset_hist28_pred7.npz"
DEFAULT_METADATA = HERE / "dataset_hist28_pred7_metadata.csv"
DEFAULT_REPORT = HERE / "reports" / "gbdt_models_report.md"


def build_features(data: np.lib.npyio.NpzFile) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    x_price = data["X_price_history"]
    x_temp_hist = data["X_temp_history"]
    x_future = data["X_future_features"]
    y = data["y"]

    hist_avg_temp = x_temp_hist.mean(axis=2, keepdims=True)
    hist_temp = np.concatenate([x_temp_hist, hist_avg_temp], axis=2)

    future_temp = x_future[:, :, :2]
    future_avg_temp = future_temp.mean(axis=2, keepdims=True)
    future_temp = np.concatenate([future_temp, future_avg_temp], axis=2)

    parts = [
        x_price.reshape(len(x_price), -1),
        hist_temp.reshape(len(hist_temp), -1),
        future_temp.reshape(len(future_temp), -1),
    ]
    x = np.concatenate(parts, axis=1).astype(np.float32)
    y_flat = y.reshape(len(y), -1).astype(np.float32)
    shapes = {
        "X_price_history": list(x_price.shape),
        "hist_temp_with_avg": list(hist_temp.shape),
        "future_temp_with_avg": list(future_temp.shape),
        "X_tabular": list(x.shape),
        "y_flat": list(y_flat.shape),
        "y_original": list(y.shape),
    }
    return x, y_flat, shapes


def persistence_predict(data: np.lib.npyio.NpzFile) -> np.ndarray:
    x_price = data["X_price_history"]
    pred_days = data["y"].shape[1]
    return x_price[:, -pred_days:, :].reshape(len(x_price), -1)


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
    return float(np.mean(2 * np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "MAE": mae(y_true, y_pred),
        "RMSE": rmse(y_true, y_pred),
        "MAPE_%": mape(y_true, y_pred),
        "sMAPE_%": smape(y_true, y_pred),
    }


def metrics_by_day(y_true_flat: np.ndarray, y_pred_flat: np.ndarray, pred_days: int = 7, periods: int = 48) -> pd.DataFrame:
    y_true = y_true_flat.reshape(len(y_true_flat), pred_days, periods)
    y_pred = y_pred_flat.reshape(len(y_pred_flat), pred_days, periods)
    rows = []
    for i in range(pred_days):
        rows.append({"forecast_day": i + 1, **metrics(y_true[:, i, :], y_pred[:, i, :])})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---:" for _ in cols]) + " |"]
    for _, row in df.iterrows():
        values = []
        for col in cols:
            value = row[col]
            values.append(str(int(value)) if col == "forecast_day" else f"{float(value):.4f}")
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def train_lightgbm(x_train: np.ndarray, y_train: np.ndarray, args: argparse.Namespace):
    base = LGBMRegressor(
        objective="regression",
        n_estimators=args.lgbm_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.lgbm_num_leaves,
        max_depth=args.max_depth,
        subsample=0.9,
        colsample_bytree=0.8,
        random_state=args.seed,
        n_jobs=1,
        verbosity=-1,
    )
    model = MultiOutputRegressor(base, n_jobs=args.multioutput_jobs)
    model.fit(x_train, y_train)
    return model


def train_xgboost(x_train: np.ndarray, y_train: np.ndarray, args: argparse.Namespace):
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=args.xgb_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        subsample=0.9,
        colsample_bytree=0.8,
        tree_method="hist",
        random_state=args.seed,
        n_jobs=args.xgb_jobs,
        multi_strategy="one_output_per_tree",
    )
    model.fit(x_train, y_train)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description="Train LightGBM and XGBoost 7-day forecasting models.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--models-dir", type=Path, default=HERE / "models")
    parser.add_argument("--predictions-dir", type=Path, default=HERE / "predictions")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--lgbm-estimators", type=int, default=80)
    parser.add_argument("--lgbm-num-leaves", type=int, default=31)
    parser.add_argument("--xgb-estimators", type=int, default=120)
    parser.add_argument("--xgb-jobs", type=int, default=4)
    parser.add_argument("--multioutput-jobs", type=int, default=1)
    parser.add_argument("--skip-lightgbm", action="store_true")
    parser.add_argument("--skip-xgboost", action="store_true")
    args = parser.parse_args()

    data = np.load(args.dataset)
    metadata = pd.read_csv(args.metadata)
    x, y, shapes = build_features(data)
    split = int(len(y) * args.train_ratio)
    x_train, x_test = x[:split], x[split:]
    y_train, y_test = y[:split], y[split:]
    persistence_test = persistence_predict(data)[split:]

    args.models_dir.mkdir(parents=True, exist_ok=True)
    args.predictions_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, float]] = {
        "Persistence": metrics(y_test, persistence_test),
    }
    by_day_tables = {
        "Persistence": metrics_by_day(y_test, persistence_test),
    }
    artifacts: dict[str, str] = {}

    if not args.skip_lightgbm:
        print("training LightGBM...")
        lgbm = train_lightgbm(x_train, y_train, args)
        lgbm_pred = lgbm.predict(x_test).astype(np.float32)
        lgbm_path = args.models_dir / "lightgbm_multioutput_hist28_pred7.joblib"
        joblib.dump(lgbm, lgbm_path)
        np.savez_compressed(args.predictions_dir / "lightgbm_predictions_test.npz", y_true=y_test, y_pred=lgbm_pred)
        results["LightGBM"] = metrics(y_test, lgbm_pred)
        by_day_tables["LightGBM"] = metrics_by_day(y_test, lgbm_pred)
        artifacts["LightGBM"] = str(lgbm_path)

    if not args.skip_xgboost:
        print("training XGBoost...")
        xgb = train_xgboost(x_train, y_train, args)
        xgb_pred = xgb.predict(x_test).astype(np.float32)
        xgb_path = args.models_dir / "xgboost_multioutput_hist28_pred7.joblib"
        joblib.dump(xgb, xgb_path)
        np.savez_compressed(args.predictions_dir / "xgboost_predictions_test.npz", y_true=y_test, y_pred=xgb_pred)
        results["XGBoost"] = metrics(y_test, xgb_pred)
        by_day_tables["XGBoost"] = metrics_by_day(y_test, xgb_pred)
        artifacts["XGBoost"] = str(xgb_path)

    summary_path = args.models_dir / "gbdt_training_summary.json"
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "metadata": str(args.metadata),
        "feature_definition": "flattened historical half-hour RRP + historical max/min/avg temp + future max/min/avg temp",
        "shapes": shapes,
        "train_ratio": args.train_ratio,
        "train_samples": split,
        "test_samples": len(y) - split,
        "test_range": {
            "start_sample_date": metadata.iloc[split]["sample_date"],
            "end_sample_date": metadata.iloc[-1]["sample_date"],
        },
        "hyperparameters": {
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "lgbm_estimators": args.lgbm_estimators,
            "xgb_estimators": args.xgb_estimators,
        },
        "metrics": results,
        "artifacts": artifacts,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    rows = []
    for model_name, metric_values in results.items():
        rows.append({"model": model_name, **metric_values})
    overall_df = pd.DataFrame(rows)
    report = [
        "# LightGBM and XGBoost 7-Day Forecast Report",
        "",
        "## Task",
        "",
        "Predict future 7 days of NSW half-hourly RRP, i.e. `7 * 48 = 336` prices per sample.",
        "",
        "## Features",
        "",
        "- Historical half-hour RRP: `28 days * 48` values.",
        "- Historical temperature: daily max, min, and average temperature for 28 days.",
        "- Future temperature: daily max, min, and average temperature for the 7 forecast days.",
        "",
        "During backtesting, future temperature uses observed temperature as a proxy for weather forecasts. For real prediction, replace it with weather forecast values.",
        "",
        "## Chronological Split",
        "",
        f"- Train samples: `{split}` from `{metadata.iloc[0]['sample_date']}` to `{metadata.iloc[split - 1]['sample_date']}`",
        f"- Test samples: `{len(y) - split}` from `{metadata.iloc[split]['sample_date']}` to `{metadata.iloc[-1]['sample_date']}`",
        "",
        "## Overall Test Metrics",
        "",
        markdown_table(overall_df),
        "",
        "## Metrics By Forecast Day",
        "",
    ]
    for model_name, table in by_day_tables.items():
        report.extend([f"### {model_name}", "", markdown_table(table), ""])
    report.extend(
        [
            "## Saved Artifacts",
            "",
            f"- Training summary: `{summary_path}`",
        ]
    )
    for model_name, path in artifacts.items():
        report.append(f"- {model_name} model weights: `{path}`")
    report.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- Persistence is the minimum baseline. A learned model should beat it on MAE/RMSE to justify added complexity.",
            "- MAPE can be very large in electricity prices because prices can be close to zero or negative; MAE/RMSE are more stable for this task.",
            "- Extreme price spikes dominate RMSE. Review both overall metrics and forecast-day metrics.",
        ]
    )
    args.report.write_text("\n".join(report), encoding="utf-8")

    print(json.dumps({"metrics": results, "report": str(args.report), "artifacts": artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
