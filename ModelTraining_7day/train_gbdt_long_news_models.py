#!/usr/bin/env python3
"""Train LightGBM/XGBoost long-format models with historical news features."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
DEFAULT_DATASET = HERE / "dataset_hist28_pred7.npz"
DEFAULT_METADATA = HERE / "dataset_hist28_pred7_metadata.csv"
DEFAULT_NEWS = ROOT / "CollectedData" / "Classified news" / "allnews2026.csv"
DEFAULT_REPORT = HERE / "reports" / "gbdt_long_models_report.md"


def parse_level(text: str) -> int | None:
    match = re.search(r"Level\s*([123])", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def read_daily_news(path: Path) -> dict[str, Counter[str]]:
    by_date: dict[str, Counter[str]] = defaultdict(Counter)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                dt = datetime.strptime(row["date"], "%d-%m-%Y %I:%M:%S %p")
            except ValueError:
                continue
            key = dt.strftime("%Y-%m-%d")
            by_date[key]["news_count"] += 1
            level = parse_level(row.get("classified_content", ""))
            if level is None:
                by_date[key]["news_unknown"] += 1
            else:
                by_date[key][f"news_level_{level}"] += 1
    return by_date


def sample_news_features(metadata: pd.DataFrame, daily_news: dict[str, Counter[str]], hist_days: int) -> tuple[np.ndarray, list[str]]:
    names = [
        "news_count_28d",
        "news_level_1_28d",
        "news_level_2_28d",
        "news_level_3_28d",
        "news_unknown_28d",
        "news_count_7d",
        "news_level_1_7d",
        "news_level_2_7d",
        "news_level_3_7d",
        "news_unknown_7d",
    ]
    rows = []
    for _, row in metadata.iterrows():
        end = pd.Timestamp(row["sample_date"])
        hist_dates = pd.date_range(end - pd.Timedelta(days=hist_days - 1), end, freq="D")
        last7_dates = hist_dates[-7:]
        c28: Counter[str] = Counter()
        c7: Counter[str] = Counter()
        for date in hist_dates:
            c28.update(daily_news.get(str(date.date()), Counter()))
        for date in last7_dates:
            c7.update(daily_news.get(str(date.date()), Counter()))
        rows.append(
            [
                c28["news_count"],
                c28["news_level_1"],
                c28["news_level_2"],
                c28["news_level_3"],
                c28["news_unknown"],
                c7["news_count"],
                c7["news_level_1"],
                c7["news_level_2"],
                c7["news_level_3"],
                c7["news_unknown"],
            ]
        )
    return np.asarray(rows, dtype=np.float32), names


def build_long_features(
    x_price: np.ndarray,
    x_temp_hist: np.ndarray,
    x_future: np.ndarray,
    y: np.ndarray,
    x_news: np.ndarray,
    news_names: list[str],
):
    n, _, periods = x_price.shape
    pred_days = y.shape[1]
    rows = n * pred_days * periods
    sample_idx = np.repeat(np.arange(n), pred_days * periods)
    day_idx = np.tile(np.repeat(np.arange(pred_days), periods), n)
    slot_idx = np.tile(np.arange(periods), n * pred_days)

    feature_names: list[str] = []
    features: list[np.ndarray] = []

    recent = x_price[:, -7:, :]
    for lag in range(7):
        feature_names.append(f"same_slot_price_lag_day_{7 - lag}")
        features.append(recent[sample_idx, lag, slot_idx])

    feature_names.extend(["same_slot_hist_mean", "same_slot_hist_std", "same_slot_hist_min", "same_slot_hist_max"])
    features.extend(
        [
            x_price.mean(axis=1)[sample_idx, slot_idx],
            x_price.std(axis=1)[sample_idx, slot_idx],
            x_price.min(axis=1)[sample_idx, slot_idx],
            x_price.max(axis=1)[sample_idx, slot_idx],
        ]
    )

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

    hist_max = x_temp_hist[:, :, 0]
    hist_min = x_temp_hist[:, :, 1]
    hist_avg = (hist_max + hist_min) / 2
    for name, arr in [("hist_max_temp", hist_max), ("hist_min_temp", hist_min), ("hist_avg_temp", hist_avg)]:
        feature_names.extend([f"{name}_mean_28d", f"{name}_last"])
        features.extend([arr.mean(axis=1)[sample_idx], arr[:, -1][sample_idx]])

    future_max = x_future[:, :, 0]
    future_min = x_future[:, :, 1]
    future_avg = (future_max + future_min) / 2
    feature_names.extend(["future_max_temp", "future_min_temp", "future_avg_temp"])
    features.extend([future_max[sample_idx, day_idx], future_min[sample_idx, day_idx], future_avg[sample_idx, day_idx]])

    for idx, name in enumerate(news_names):
        feature_names.append(name)
        features.append(x_news[sample_idx, idx])

    slot_angle = 2 * math.pi * slot_idx / periods
    day_angle = 2 * math.pi * day_idx / pred_days
    feature_names.extend(["forecast_day", "slot", "slot_sin", "slot_cos", "forecast_day_sin", "forecast_day_cos"])
    features.extend([day_idx + 1, slot_idx, np.sin(slot_angle), np.cos(slot_angle), np.sin(day_angle), np.cos(day_angle)])

    x_long = np.column_stack(features).astype(np.float32)
    y_long = y.reshape(rows).astype(np.float32)
    index = np.column_stack([sample_idx, day_idx, slot_idx]).astype(np.int32)
    return x_long, y_long, index, feature_names


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


def predict_grid(model, x_long: np.ndarray, n_samples: int, pred_days: int = 7, periods: int = 48) -> np.ndarray:
    return model.predict(x_long).astype(np.float32).reshape(n_samples, pred_days, periods)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train long-format GBDT models with news features.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--news", type=Path, default=DEFAULT_NEWS)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--models-dir", type=Path, default=HERE / "models")
    parser.add_argument("--predictions-dir", type=Path, default=HERE / "predictions")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lgbm-estimators", type=int, default=200)
    parser.add_argument("--xgb-estimators", type=int, default=200)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--n-jobs", type=int, default=4)
    args = parser.parse_args()

    data = np.load(args.dataset)
    metadata = pd.read_csv(args.metadata)
    daily_news = read_daily_news(args.news)
    x_news, news_names = sample_news_features(metadata, daily_news, hist_days=data["X_price_history"].shape[1])

    x_long, y_long, index, feature_names = build_long_features(
        data["X_price_history"],
        data["X_temp_history"],
        data["X_future_features"],
        data["y"],
        x_news,
        news_names,
    )
    y = data["y"]
    split = int(len(y) * args.train_ratio)
    train_mask = index[:, 0] < split
    test_mask = ~train_mask
    x_train, y_train = x_long[train_mask], y_long[train_mask]
    x_test = x_long[test_mask]
    y_test = y[split:]

    args.models_dir.mkdir(parents=True, exist_ok=True)
    args.predictions_dir.mkdir(parents=True, exist_ok=True)

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
    print("training LightGBM with news features...")
    lgbm.fit(x_train, y_train, feature_name=feature_names)
    lgbm_pred = predict_grid(lgbm, x_test, n_samples=len(y_test))
    lgbm_path = args.models_dir / "lightgbm_long_news_hist28_pred7.joblib"
    joblib.dump({"model": lgbm, "feature_names": feature_names, "news_features": news_names}, lgbm_path)
    np.savez_compressed(args.predictions_dir / "lightgbm_long_news_predictions_test.npz", y_true=y_test, y_pred=lgbm_pred)

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
    print("training XGBoost with news features...")
    xgb.fit(x_train, y_train)
    xgb_pred = predict_grid(xgb, x_test, n_samples=len(y_test))
    xgb_path = args.models_dir / "xgboost_long_news_hist28_pred7.joblib"
    joblib.dump({"model": xgb, "feature_names": feature_names, "news_features": news_names}, xgb_path)
    np.savez_compressed(args.predictions_dir / "xgboost_long_news_predictions_test.npz", y_true=y_test, y_pred=xgb_pred)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "news": str(args.news),
        "feature_definition": "direct multi-step long-format model with historical price, temperature, and historical news features",
        "news_features": news_names,
        "train_samples": split,
        "test_samples": len(y) - split,
        "metrics": {
            "LightGBM_news": metric_dict(y_test, lgbm_pred),
            "XGBoost_news": metric_dict(y_test, xgb_pred),
        },
        "artifacts": {
            "LightGBM_news": str(lgbm_path),
            "XGBoost_news": str(xgb_path),
        },
    }
    summary_path = args.models_dir / "gbdt_long_news_training_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
