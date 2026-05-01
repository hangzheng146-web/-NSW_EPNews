# Persistence Baseline Report

## Task

Predict future 7 days of NSW half-hourly RRP:

```text
output shape per sample = 7 days * 48 half-hour prices = 336 values
```

## Data

- Dataset: `dataset_hist28_pred7.npz`
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
| Train | 3253 | 2015-01-28 to 2023-12-24 |
| Test | 814 | 2023-12-25 to 2026-04-21 |

## Overall Test Metrics

| Metric | Value |
|---|---:|
| MAE | 87.3037 |
| RMSE | 688.3521 |
| MAPE % | 1396.7224 |
| sMAPE % | 66.1531 |

## Metrics By Forecast Day

| forecast_day | MAE | RMSE | MAPE_% | sMAPE_% |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 87.3886 | 688.3583 | 1394.8527 | 66.2303 |
| 2 | 87.3569 | 688.3563 | 1394.8704 | 66.2131 |
| 3 | 87.3677 | 688.3580 | 1394.8302 | 66.2305 |
| 4 | 87.3018 | 688.3520 | 1394.8878 | 66.1627 |
| 5 | 87.2573 | 688.3489 | 1393.1035 | 66.0621 |
| 6 | 87.2496 | 688.3488 | 1402.2516 | 66.0872 |
| 7 | 87.2043 | 688.3423 | 1402.2598 | 66.0857 |

## Saved Artifacts

- Model artifact: `/Users/dezhen/Desktop/EFP2/ NSW_EPNews/ModelTraining_7day/models/persistence_baseline_model.json`
- Test predictions: `/Users/dezhen/Desktop/EFP2/ NSW_EPNews/ModelTraining_7day/predictions/persistence_baseline_predictions_test.npz`

## Interpretation

This baseline measures weekly price-pattern persistence. If later models using temperature and richer history cannot beat this MAE/RMSE on the same chronological test split, they are not adding useful predictive signal.

The model has no trainable weights. The saved JSON artifact records the exact persistence rule, input shapes, split index, and evaluation metrics so the baseline is reproducible.
