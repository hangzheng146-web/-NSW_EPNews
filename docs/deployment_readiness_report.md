# Render 部署就绪检查报告

本文只做检查和结论，不重构项目。

## 1. 当前项目启动入口

当前网页后端的启动入口是：

```text
ForecastDashboard/server.py
```

该文件底部的 `main()` 会启动 `ThreadingHTTPServer`。

当前本地启动方式支持：

- `HOST`
- `PORT`

也就是：

```bash
cd ForecastDashboard && HOST=0.0.0.0 python server.py
```

## 2. 当前 requirements 文件位置

当前 `requirements.txt` 的位置是项目根目录：

```text
requirements.txt
```

不是放在子目录里。

## 3. 是否存在本地绝对路径

结论：**存在，但主要集中在文档和本地运行示例中，不影响当前主流程部署**。

检查结果：

- 运行代码主体大多使用相对路径，例如 `ROOT / "ModelTraining_7day" / "models"`。
- 部分文档里出现了本机路径示例，例如 `/Users/dezhen/Desktop/EFP2/...`。

这类路径对本地说明没有问题，但不建议作为云部署依赖。

## 4. 是否存在写死端口

结论：**运行服务本身不再写死端口；策略运行时也已改为跟随当前请求来源，不再依赖本地 8765**。

当前服务启动端口读取：

```python
host = os.environ.get("HOST", "127.0.0.1")
port = int(os.environ.get("PORT", "8765"))
```

所以主服务监听端口支持环境变量。

策略运行函数现在会优先使用当前请求的 `Host` 和 `X-Forwarded-Proto` 组装 forecast URL，因此本地和云端都能回到同一个服务地址。

## 5. 是否支持 PORT 环境变量

结论：**支持**。

`ForecastDashboard/server.py` 已读取：

```python
os.environ.get("PORT", "8765")
```

因此符合 Render 的常见部署方式。

## 6. 是否支持 0.0.0.0 监听

结论：**支持**。

主服务可以通过：

```bash
HOST=0.0.0.0
```

进行监听，这也是 Render 推荐方式。

## 7. 是否依赖本地 outputs 文件

结论：**是**。

Battery Strategy 前端展示依赖：

- `BatteryStrategy/outputs/battery_parameters.csv`
- `BatteryStrategy/outputs/price_forecast_used.csv`
- `BatteryStrategy/outputs/battery_dispatch_result.csv`
- `BatteryStrategy/outputs/soc_curve.csv`
- `BatteryStrategy/outputs/revenue_summary.csv`
- `BatteryStrategy/outputs/validation_checks.txt`
- `BatteryStrategy/outputs/run_metadata.json`

同时，按日期运行后还会写入：

```text
BatteryStrategy/runs/YYYY-MM-DD/
```

如果这些文件不存在，Battery Strategy 区域就无法完整展示。

## 8. 是否依赖大模型文件

结论：**是**。

预测 API 会加载模型摘要和模型权重文件，主要来自：

- `ModelTraining_7day/models/gbdt_long_training_summary.json`
- `ModelTraining_7day/models/gbdt_long_news_training_summary.json`
- 对应的 `joblib` 模型文件

其中 `server.py` 会根据摘要文件挑选 MAE 最优模型并加载。

## 9. 是否有大文件不适合上传 GitHub

结论：**有，而且数量不少**。

当前项目里体积较大的目录包括：

- `ModelTraining_7day/models`，约 273M
- `CollectedData`，约 261M
- `DATASET for experiment`，约 227M

另外还发现一些不建议直接上传的内容：

- 历史 notebooks
- 临时运行输出
- 大型训练中间文件

如果目标是把仓库交给别人看或部署，建议区分：

- 必需源码
- 必需模型文件
- 必需运行数据
- 不需要提交的训练中间产物

## 10. 是否有 API Key 泄露风险

结论：**有风险，需要继续处理**。

检查到的风险点：

1. notebook 里存在硬编码密钥痕迹。
2. 文档里会出现 `DEEPSEEK_API_KEY` 这类变量名，这是正常的，但不应出现真实值。

目前 `.gitignore` 已经忽略：

- `.env`
- `.env.local`
- `*.ipynb`

但如果这些 notebook 曾经提交过，仍然需要人工确认历史记录。

## 11. 需要在 Render 配置哪些环境变量

至少建议配置：

```text
HOST=0.0.0.0
DEEPSEEK_API_KEY=你的真实值
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

如果后续页面或脚本要调用其他模型服务，再补充：

```text
DASHSCOPE_API_KEY
SILICONFLOW_API_KEY
OPENAI_API_KEY
```

注意：

- 真正部署到 Render 时，`PORT` 通常由平台自动提供，不需要你手工填写固定值。
- 真实 Key 只放 Render 环境变量，不写进 GitHub。

## 12. 当前是否建议立即部署

结论：**代码层面已经接近可部署，但正式上线前仍建议做一次 GitHub 安全整理，再部署到 Render**。

当前已经修掉的关键问题：

### 仍然需要注意的事项 1：仓库体积过大

项目包含大量数据和模型文件，上传和部署成本都偏高。

### 仍然需要注意的事项 2：历史 notebook 里有硬编码 API Key 风险

即使 `.gitignore` 已经覆盖，仍建议先确认不会进入 Git 历史。

## 13. 如果不建议，最小修复清单是什么

最小修复建议如下，不做大改：

1. 再做一次密钥扫描，重点确认：
   - `*.ipynb`
   - `.env`
   - `.env.local`
   - 代码和文档里没有真实 Key

2. 明确哪些大文件要随仓库一起部署，哪些只保留在本地。

3. 如果你希望 Render 上也能稳定运行 Battery Strategy 区域，确认 `BatteryStrategy/runs/` 和 `BatteryStrategy/outputs/` 的生成逻辑在云端可用。

## 总结

当前项目已经满足：

- 有明确入口
- 支持 `HOST`
- 支持 `PORT`
- 依赖已列在 `requirements.txt`

但还不算“完全无风险”的状态，主要还要注意：

- 仓库体积较大
- notebook 里有历史 API Key 风险
- 部署前仍需确认大文件是否都要进入 GitHub

当前这版已经修掉了写死本地 forecast URL 的问题，可以进入下一轮部署验证。
