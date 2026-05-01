# GitHub 上传说明

本文用于在把项目上传到 GitHub 之前做安全检查，并给出一套可直接照着执行的上传步骤。

## 1. 上传 GitHub 前检查

上传前先确认以下内容：

1. `.env` 和 `.env.local` 不会被提交。
2. 真实 API Key 不在代码里。
3. `.gitignore` 已经生效。
4. `requirements.txt` 存在。
5. 根目录 `README.md` 存在。

建议先在项目根目录执行：

```bash
git status
```

重点检查输出里是否出现：

```text
.env
.env.local
```

如果出现，先不要提交，先修正 `.gitignore` 或把文件从 Git 跟踪中移除。

也建议全局搜索这些关键词，确认没有真实密钥泄露：

```text
DEEPSEEK_API_KEY
API_KEY
.env
sk-
```

## 2. GitHub 网页创建仓库步骤

1. 登录 GitHub。
2. 点击右上角 `+`。
3. 选择 `New repository`。
4. 填写仓库名。
5. 建议先选择 `Private`。
6. 如果本地已经有 `README.md`，不要勾选自动生成 `README`。

如果你本地已经准备好项目文件，建议 GitHub 仓库保持空仓库状态，避免和本地文件冲突。

## 3. 本地上传命令示例

在项目根目录执行：

```bash
git init
git status
git add .
git commit -m "Initial project version"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

如果仓库已经初始化过，就不需要重复执行 `git init`。

## 4. 如果 `git status` 显示 `.env` 或 `.env.local` 被追踪

这时要先停止提交，不要继续 `git add .` 或 `git commit`。

先检查 `.gitignore` 是否包含：

```text
.env
.env.local
```

如果已经写了 `.gitignore` 但文件仍被追踪，说明这些文件之前已经进入 Git 索引。此时要先移除追踪，再提交。常见处理方式是：

```bash
git rm --cached .env
git rm --cached .env.local
```

然后再检查：

```bash
git status
```

确认 `.env` 和 `.env.local` 不再出现在待提交列表里。

## 5. 上传后如何在 GitHub 页面检查

上传完成后，在 GitHub 页面检查以下内容：

1. 搜索 `DEEPSEEK_API_KEY`。
2. 搜索 `API_KEY`。
3. 搜索 `.env`。
4. 确认没有真实密钥泄露。

如果仓库公开，建议再确认这些路径没有被误上传：

```text
.env
.env.local
BatteryStrategy/runs/
BatteryStrategy/outputs/
ModelTraining_7day/dataset_hist28_pred7.npz
ModelTraining_7day/models/arima_slotwise_48models.joblib
```

## 6. 补充说明

这个项目包含模型、数据和前端后端代码，体积比较大。上传前要特别注意：

1. 不要把真实 API Key 写进代码。
2. 不要把本地环境文件提交到 GitHub。
3. 不要把临时运行结果目录当作长期源码上传。
4. 如果某些大文件后续不需要放进仓库，可以先放到 `.gitignore` 里。

如果你后续要部署到 Render，建议把部署说明、环境变量说明和运行命令都保留在仓库文档中，方便以后回溯。
