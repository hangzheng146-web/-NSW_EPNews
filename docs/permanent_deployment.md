# 永久网页部署说明

## 1. 为什么不能用 GitHub Pages

当前页面不是纯静态页面。它依赖 Python 后端：

```text
ForecastDashboard/server.py
```

后端需要：

- 加载训练好的 LightGBM/XGBoost 模型
- 读取本地 CSV 数据
- 调用 AEMO / BoM 数据源
- 运行 BatteryStrategy 策略脚本
- 提供 `/api/forecast` 和 `/api/battery-strategy/run`

因此需要部署到能运行 Python Web Service 的平台，例如 Render、Railway、Fly.io 或云服务器。

## 2. 已新增部署文件

```text
requirements.txt
Procfile
render.yaml
docs/permanent_deployment.md
```

后端也已支持云平台常见的 `PORT` 环境变量。

## 3. 推荐部署目录

部署根目录应为：

```text
NSW_EPNews
```

注意：你本机目录名现在是：

```text
/Users/dezhen/Desktop/EFP2/ NSW_EPNews
```

前面有一个空格。上传到 GitHub 或云平台前，建议把项目目录重命名为：

```text
NSW_EPNews
```

## 4. 必须包含的关键文件

前端和后端：

```text
ForecastDashboard/
BatteryStrategy/
docs/
requirements.txt
Procfile
render.yaml
```

模型文件至少需要：

```text
ModelTraining_7day/models/gbdt_long_training_summary.json
ModelTraining_7day/models/gbdt_long_news_training_summary.json
ModelTraining_7day/models/lightgbm_long_hist28_pred7.joblib
ModelTraining_7day/models/xgboost_long_hist28_pred7.joblib
ModelTraining_7day/models/lightgbm_long_news_hist28_pred7.joblib
ModelTraining_7day/models/xgboost_long_news_hist28_pred7.joblib
```

数据文件至少需要：

```text
CollectedData/Electricity prices from NEM/unified_price_data/unified_used_for_experiment/2015To2026Data.csv
CollectedData/Temperature/max_temps_2015_2026.csv
CollectedData/Temperature/min_temps_2015_2026.csv
```

## 5. 可以先不上传的大文件

为了降低部署体积，以下文件不是当前前端预测必需：

```text
ModelTraining_7day/models/arima_slotwise_48models.joblib
ModelTraining_7day/dataset_hist28_pred7.npz
ModelTraining_7day/predictions/
```

当前项目总目录较大，建议先做一个精简部署仓库，只放运行网页需要的文件。

## 6. Render 部署参数

如果使用 Render Web Service：

```text
Build Command:
pip install -r requirements.txt

Start Command:
cd ForecastDashboard && HOST=0.0.0.0 python server.py
```

部署后访问：

```text
https://你的服务名.onrender.com/index.html
```

## 7. 本地验证部署启动方式

在本地模拟云平台启动：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
HOST=0.0.0.0 PORT=8765 /Users/dezhen/Desktop/EFP2/.venv/bin/python ForecastDashboard/server.py
```

然后打开：

```text
http://127.0.0.1:8765/index.html
```

## 8. 注意事项

永久部署需要你自己的云平台账号。

临时 Cloudflare Tunnel 链接只适合演示，不适合长期分享。永久网页应该部署到 Python Web Service 平台。
