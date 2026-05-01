# 储能套利策略原型说明

## 1. 模块定位

本模块是第一版规则型储能套利策略原型。

它不训练模型，也不改动现有 7 天电价预测主流程。它只读取已经生成的未来 7 天、每日 48 个半小时预测电价点，然后根据简单阈值规则和电池约束，计算一个可检查的充放电结果。

当前目标是回答：

- 哪些预测低价点会触发充电？
- 哪些预测高价点会触发放电？
- SOC、功率、效率约束会不会限制实际动作？
- 按当前规则粗略计算，充电成本、放电收入、循环成本和净收益是多少？

## 2. 输入数据

输入是预测 JSON，要求包含 `point_forecast` 字段。

每个预测点至少需要：

```json
{
  "timestamp": "2026-05-01 00:00",
  "date": "2026-05-01",
  "half_hour_index": 0,
  "predicted_price": 79.74
}
```

标准输入长度是：

```text
7 天 * 每天 48 个半小时 = 336 个预测价格点
```

默认输入文件：

```bash
ForecastDashboard/forecast_sample.json
```

也可以直接读取现有预测 API：

```bash
http://127.0.0.1:8765/api/forecast?forecast_start=2026-05-01
```

## 3. 电池参数

第一版使用固定假设参数：

| 参数 | 数值 | 单位 |
|---|---:|---|
| 电池容量 | 100 | MWh |
| 最大充电功率 | 50 | MW |
| 最大放电功率 | 50 | MW |
| 初始 SOC | 50 | MWh |
| 最低 SOC | 10 | MWh |
| 最高 SOC | 90 | MWh |
| 充电效率 | 0.95 | ratio |
| 放电效率 | 0.95 | ratio |
| 循环成本 | 10 | AUD/MWh |
| 时间间隔 | 0.5 | hour |

## 4. 策略规则

规则只基于预测价格：

```text
预测价格 < 30 AUD/MWh -> charge
预测价格 > 150 AUD/MWh -> discharge
预测价格 > 300 AUD/MWh -> spike risk
其他情况 -> idle
```

注意：

- `spike risk` 是风险标记。
- 如果价格高于 300 AUD/MWh，它同时也满足高价放电条件。
- 最终是否真的能充放电，还要看 SOC 和功率约束。

## 5. SOC 和收益计算

每个半小时按 0.5 小时计算。

充电时：

```text
电网买电量 MWh = charge_mw * 0.5
SOC 增加量 = 电网买电量 * 充电效率
充电成本 = predicted_price * 电网买电量
```

放电时：

```text
电网卖电量 MWh = discharge_mw * 0.5
SOC 减少量 = 电网卖电量 / 放电效率
放电收入 = predicted_price * 电网卖电量
循环成本 = cycle_cost * 电网卖电量
```

净收益：

```text
net_revenue = 放电收入 - 充电成本 - 循环成本
```

## 6. 输出文件

运行后会输出到：

```bash
BatteryStrategy/outputs/
```

包含：

```text
battery_parameters.csv
price_forecast_used.csv
battery_dispatch_result.csv
soc_curve.csv
revenue_summary.csv
validation_checks.txt
```

各文件含义：

- `battery_parameters.csv`：本次使用的电池参数和阈值。
- `price_forecast_used.csv`：实际用于策略计算的 336 个预测价格点，以及初始规则信号。
- `battery_dispatch_result.csv`：每个半小时的规则信号、实际充放电功率、SOC、成本、收入、循环成本和净收益。
- `soc_curve.csv`：每个半小时的 SOC 起点和终点。
- `revenue_summary.csv`：总充电量、总放电量、总成本、总收入、总循环成本、总净收益等汇总指标。
- `validation_checks.txt`：检查 SOC 是否越界、功率是否越界、是否同时充放电、预测点数量是否为 336。

## 7. 运行命令

使用默认样本预测文件：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
/Users/dezhen/Desktop/EFP2/.venv/bin/python BatteryStrategy/run_battery_strategy.py
```

使用当前本地预测 API：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
/Users/dezhen/Desktop/EFP2/.venv/bin/python BatteryStrategy/run_battery_strategy.py \
  --forecast-json "http://127.0.0.1:8765/api/forecast?forecast_start=2026-05-01"
```

指定输出目录：

```bash
/Users/dezhen/Desktop/EFP2/.venv/bin/python BatteryStrategy/run_battery_strategy.py \
  --forecast-json "http://127.0.0.1:8765/api/forecast?forecast_start=2026-05-01" \
  --output-dir BatteryStrategy/outputs_20260501
```

## 8. 检查方法

先看：

```bash
cat BatteryStrategy/outputs/validation_checks.txt
```

如果最后是：

```text
status: PASS
```

说明没有发现 SOC 越界、功率越界或同时充放电。

再看收益汇总：

```bash
cat BatteryStrategy/outputs/revenue_summary.csv
```

重点关注：

```text
total_charge_cost
total_discharge_revenue
total_cycle_cost
total_net_revenue
charge_intervals
discharge_intervals
spike_risk_intervals
```

最后看逐半小时结果：

```bash
head BatteryStrategy/outputs/battery_dispatch_result.csv
```

## 9. 当前局限

这个版本是规则策略，不是最优策略。

主要局限：

- 只用固定阈值判断，不会自动寻找全局最优峰谷组合。
- 不考虑预测误差和价格置信区间。
- 不考虑 FCAS、合同、网络费、交易费、市场结算规则。
- 不考虑电池退化的复杂模型，只用固定循环成本近似。
- 不考虑电池必须保留备用电量的真实运营要求。
- 不考虑同一天多次循环对寿命的限制。

下一阶段可以升级为线性规划或混合整数规划模型，让模型在 SOC、功率和效率约束下自动最大化未来 7 天净收益。
