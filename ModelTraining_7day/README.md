# NSW 7-Day Half-Hour Electricity Price Forecasting

This folder is for model training data and experiments targeting:

```text
Input  -> historical NSW half-hour prices + historical temperatures + future temperature/calendar features
Output -> next 7 days of NSW half-hour RRP, 7 * 48 = 336 values
```

## Source Data

- Prices: `../CollectedData/Electricity prices from NEM/unified_price_data/unified_used_for_experiment/2015To2026Data.csv`
- Max temperature: `../CollectedData/Temperature/max_temps_2015_2026.csv`
- Min temperature: `../CollectedData/Temperature/min_temps_2015_2026.csv`

The price file is filtered to `REGION == NSW1`. Temperature is averaged across stations per day.

## Recommended Modeling Order

1. Persistence baseline
   - Repeat the most recent 7 days of prices as the next 7 days.
   - This is the minimum benchmark any model should beat.

2. Gradient boosting direct multi-horizon baseline
   - Train one model per forecast horizon, or use a multi-output wrapper.
   - Good first production-style baseline with tabular features.
   - Suitable libraries: LightGBM, XGBoost, scikit-learn HistGradientBoosting.

3. Sequence models
   - LSTM/GRU encoder-decoder, N-BEATS/N-HiTS, Temporal Fusion Transformer.
   - Better suited once the baseline is reliable and enough data/features exist.

## Dataset Shape

The builder creates:

```text
X_price_history:   [samples, hist_days, 48]
X_temp_history:    [samples, hist_days, 2]      # max/min temp
X_future_features: [samples, pred_days, 6]      # future max/min temp + calendar sin/cos
y:                 [samples, pred_days, 48]
```

Default:

```text
hist_days = 28
pred_days = 7
```

For real future prediction, `X_future_features` should use weather forecasts for the next 7 days. During backtesting, it uses observed future temperature as a proxy for forecast temperature.
