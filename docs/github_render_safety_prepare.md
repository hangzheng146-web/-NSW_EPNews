# GitHub 上传与 Render 部署前安全准备说明

## 1. 本次整理目标

本项目已经整理为更适合上传 GitHub 和后续部署 Render 的状态。

本次没有改动：

- 电价预测模型主流程
- BatteryStrategy 主流程
- 前端核心展示逻辑

本次新增：

```text
.gitignore
.env.example
docs/github_render_safety_prepare.md
```

## 2. 安全扫描结果

当前项目中发现历史 Notebook 里存在硬编码 API Key 风险，包括：

```text
NSW-EPNEWS_ExperimentCodebase/Elecprice_Gemini.ipynb
NSW-EPNEWS_ExperimentCodebase/chatgpt4o.ipynb
```

这些 Notebook 已经通过 `.gitignore` 排除：

```text
*.ipynb
.ipynb_checkpoints/
```

因此新建 Git 仓库后，默认不会被提交。

重要：如果你之前已经把这些 Notebook 提交过 GitHub，需要立刻撤销对应 API Key，并清理 Git 历史。

## 3. 绝对不能提交到 GitHub 的内容

不要提交：

```text
.env
.env.local
DeepSeek API Key
OpenAI API Key
DashScope Key
SiliconFlow Key
任何包含真实 key 的 txt/json/yaml 文件
```

本项目已新增 `.gitignore` 来排除：

```text
.env
.env.*
*secret*
*api_key*
*apikey*
*key.txt
*.ipynb
```

`.env.example` 可以提交，因为里面只有占位符，没有真实 Key。

## 4. DeepSeek API Key 如何配置

新闻抓取脚本已经支持环境变量：

```text
DEEPSEEK_API_KEY
```

本地临时运行方式：

```bash
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY="你的真实 DeepSeek Key"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-chat"
```

然后运行：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
/Users/dezhen/Desktop/EFP2/.venv/bin/python NSW-EPNEWS_ExperimentCodebase/scrape_classify_news.py \
  --provider deepseek \
  --years 2025 2026
```

也可以创建本地 `.env` 文件，但 `.env` 不要上传 GitHub。

示例文件：

```text
.env.example
```

## 5. GitHub 上传前建议保留的核心文件

前端和后端：

```text
ForecastDashboard/
BatteryStrategy/
docs/
requirements.txt
Procfile
render.yaml
.gitignore
.env.example
```

模型文件：

```text
ModelTraining_7day/models/gbdt_long_training_summary.json
ModelTraining_7day/models/gbdt_long_news_training_summary.json
ModelTraining_7day/models/lightgbm_long_hist28_pred7.joblib
ModelTraining_7day/models/xgboost_long_hist28_pred7.joblib
ModelTraining_7day/models/lightgbm_long_news_hist28_pred7.joblib
ModelTraining_7day/models/xgboost_long_news_hist28_pred7.joblib
```

数据文件：

```text
CollectedData/Electricity prices from NEM/unified_price_data/unified_used_for_experiment/2015To2026Data.csv
CollectedData/Temperature/max_temps_2015_2026.csv
CollectedData/Temperature/min_temps_2015_2026.csv
```

## 6. 已排除的大文件和中间结果

`.gitignore` 已排除：

```text
ModelTraining_7day/models/arima_slotwise_48models.joblib
ModelTraining_7day/dataset_hist28_pred7.npz
ModelTraining_7day/predictions/
DATASET for experiment/
ResultCSV/
BatteryStrategy/runs/
BatteryStrategy/outputs/
```

原因：

- 这些不是当前前端部署的必需文件
- 文件体积较大
- 部分文件可能包含 LLM prompt 或实验中间结果
- BatteryStrategy 运行结果应由部署后的服务重新生成

## 7. 上传 GitHub 前检查命令

在项目根目录运行：

```bash
cd "/Users/dezhen/Desktop/EFP2/ NSW_EPNews"
git status --short
```

查看将要提交的文件：

```bash
git add --dry-run .
```

检查是否还有疑似 Key：

```bash
rg -n "sk-|DEEPSEEK_API_KEY=.+[A-Za-z0-9]|OPENAI_API_KEY=.+[A-Za-z0-9]|DASHSCOPE_API_KEY=.+[A-Za-z0-9]|SILICONFLOW_API_KEY=.+[A-Za-z0-9]" .
```

如果输出真实 Key，不要提交。

## 8. GitHub 上传建议

建议创建私有仓库：

```text
Repository visibility: Private
```

首次提交前确认：

```bash
git status --short
git add --dry-run .
```

确认没有 `.env`、Notebook、巨大中间数据后，再提交。

## 9. Render 部署准备

你暂时没有 Render 账号，所以当前只准备部署文件。

以后创建 Render 账号后，使用：

```text
Build Command:
pip install -r requirements.txt

Start Command:
cd ForecastDashboard && HOST=0.0.0.0 python server.py
```

Render 环境变量可以先不配置 DeepSeek，因为当前网页预测和 BatteryStrategy 展示不依赖 DeepSeek。

如果以后要在 Render 上运行新闻抓取，再添加：

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的真实 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

注意：环境变量应该在 Render Dashboard 配置，不要写进代码。

## 10. 当前推荐流程

1. 先用 `.gitignore` 检查上传内容。
2. 创建 GitHub Private 仓库。
3. 上传项目。
4. 等你创建 Render 账号后，再按 `docs/permanent_deployment.md` 部署。
5. Render 部署成功后，把 Render 提供的 URL 分享给别人。
