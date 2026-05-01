# 储能策略结果前端展示说明

## 1. 页面定位

本页面新增了 `Battery Strategy / 储能策略模拟` 区域，用于展示规则版储能套利策略模块已经生成的结果。

该展示区域默认可读取：

```text
BatteryStrategy/outputs/
```

中的 CSV 和 txt 文件。现在页面也支持用户点击按钮后，按当前预测日期运行策略，并把结果保存到独立 run 目录：

```text
BatteryStrategy/runs/YYYY-MM-DD/
```

该流程不重新训练模型，不改动现有电价预测主流程。

## 2. 数据来源和回溯关系

前端展示数据通过独立接口读取。

读取默认结果：

```text
/api/battery-strategy
```

按当前预测日期运行并读取结果：

```text
/api/battery-strategy/run?forecast_start=YYYY-MM-DD
```

第二个接口会由后端调用：

```text
BatteryStrategy/run_battery_strategy.py
```

并把输出写入：

```text
BatteryStrategy/runs/YYYY-MM-DD/
```

接口读取以下文件：

```text
battery_parameters.csv
price_forecast_used.csv
battery_dispatch_result.csv
soc_curve.csv
revenue_summary.csv
validation_checks.txt
run_metadata.json
```

页面展示对应关系：

| 页面区域 | 来源文件 |
|---|---|
| 电池参数 | `battery_parameters.csv` |
| 总充电量、总放电量、成本、收入、净收益 | `revenue_summary.csv` |
| 策略动作统计 | `price_forecast_used.csv`、`battery_dispatch_result.csv`、`soc_curve.csv` |
| 前 48 个半小时调度结果 | `battery_dispatch_result.csv` |
| SOC 曲线 | `soc_curve.csv` |
| 校验状态和错误信息 | `validation_checks.txt` |
| 当前 run_id、输出目录、运行命令 | `run_metadata.json` |

## 3. 运行储能策略结果生成脚本

先确保本地预测服务在运行：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews/ForecastDashboard"
/Users/dezhen/Desktop/EFP2/.venv/bin/python server.py
```

然后运行储能策略脚本：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
/Users/dezhen/Desktop/EFP2/.venv/bin/python BatteryStrategy/run_battery_strategy.py \
  --forecast-json "http://127.0.0.1:8765/api/forecast?forecast_start=2026-05-01" \
  --output-dir BatteryStrategy/outputs
```

运行后会更新：

```text
BatteryStrategy/outputs/
```

中的结果文件。

## 4. 打开前端页面

本地访问：

```text
http://127.0.0.1:8765/index.html
```

页面下方会出现：

```text
Battery Strategy / 储能策略模拟
```

当用户选择新的 `forecast_start_date` 时，页面只刷新预测展示区域。储能策略区域会显示“待运行”。用户需要点击：

```text
运行储能策略模拟
```

按钮后，后端才会运行 `BatteryStrategy/run_battery_strategy.py` 并刷新策略展示。

策略展示区域包含：

- 策略结果来源卡片：页面预测日期、策略结果日期、run_id、output_dir、generated_at、validation status。
- 策略总览卡片：总净收益、总充电量、总放电量、充电次数、放电次数、空闲次数、最终 SOC、校验状态。
- 前 48 个半小时调度表：timestamp、predicted_price、动作、充电量、放电量、SOC 起点、SOC 终点、净收益。
- SOC 曲线：展示 SOC，并绘制 10 MWh 和 90 MWh 参考线。
- validation_checks 原文。
- 结果解释区：说明当前是规则版策略，不是最优交易策略。

## 5. 验证方法

验证 API：

```bash
curl -s "http://127.0.0.1:8765/api/battery-strategy/run?forecast_start=2026-05-01"
```

检查校验文件：

```bash
cat BatteryStrategy/runs/2026-05-01/validation_checks.txt
cat BatteryStrategy/runs/2026-05-01/run_metadata.json
```

如果看到：

```text
status: PASS
```

说明当前策略输出没有发现 SOC 越界、功率越界或同时充放电。

## 6. 当前解释口径

当前前端展示的是规则版策略结果，不是最终交易指令。

规则是：

```text
预测价格 < 30 AUD/MWh -> charge
预测价格 > 150 AUD/MWh -> discharge
预测价格 > 300 AUD/MWh -> spike risk
```

实际执行还要满足：

```text
SOC 范围
最大充电功率
最大放电功率
充电效率
放电效率
循环成本
```

如果页面显示净收益为负，通常表示：

```text
规则触发了充电，但预测期内没有触发高价放电，所以只有充电成本，没有放电收入。
```

## 7. 当前局限

当前页面选择新的 `forecast_start_date` 后，只会先刷新预测结果，不会自动运行储能策略。

用户点击“运行储能策略模拟”后，前端才调用：

```text
/api/battery-strategy/run?forecast_start=YYYY-MM-DD
```

因此每个日期都会保留独立输出目录，例如：

```text
BatteryStrategy/runs/2026-05-01/
BatteryStrategy/runs/2026-05-02/
```

默认目录不会被覆盖：

```text
BatteryStrategy/outputs/
```

页面顶部的“可回溯目录”会显示当前展示结果来自哪个具体路径。
