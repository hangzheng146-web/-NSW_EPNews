# Render 部署说明

本文用于把当前项目部署到 Render。文档先讲清楚 Render 的作用，再给出创建服务、配置环境变量、启动命令和部署后验证方法。

## 一、Render 是干什么的

Render 是一个云部署平台，适合长期运行 Python Web 服务。

在这个项目里：

- GitHub 负责存放代码
- Render 负责持续运行后端服务和网页

本项目不是纯静态网页，因为它包含 Python 后端 API，例如：

- `/api/forecast`
- `/api/battery-strategy`
- `/api/battery-strategy/run`

所以 **GitHub Pages 不适合直接部署这个项目**。GitHub Pages 只适合静态 HTML/CSS/JS，不适合运行 Python API。

## 二、注册 Render

如果你还没有 Render 账号，可以后面再注册，不影响先准备部署文档。

步骤如下：

1. 打开 `https://render.com`
2. 使用 GitHub 账号注册或登录
3. 授权 Render 访问你的 GitHub 仓库

如果后续要部署私有仓库，Render 也需要 GitHub 授权。

## 三、创建 Web Service

部署时在 Render Dashboard 中：

1. 点击 `New`
2. 选择 `Web Service`
3. 选择你的 GitHub 仓库
4. 选择 branch：`main`

如果仓库还没上传到 GitHub，先完成 GitHub 上传，再回到 Render。

## 四、Build Command

根据当前项目实际结构，`requirements.txt` 在项目根目录：

```bash
pip install -r requirements.txt
```

当前仓库根目录已经有：

- `requirements.txt`
- `README.md`
- `Procfile`
- `render.yaml`

所以 Render 的 Build Command 建议直接使用上面的命令。

## 五、Start Command

当前项目的实际启动入口是：

- `ForecastDashboard/server.py`

本地启动方式也是从 `ForecastDashboard` 目录启动该文件。

Render 推荐的 Start Command 是：

```bash
cd ForecastDashboard && HOST=0.0.0.0 python server.py
```

### 为什么是这个命令

我检查过当前代码，`ForecastDashboard/server.py` 已经支持：

- `HOST`
- `PORT`

代码里会读取环境变量：

```python
host = os.environ.get("HOST", "127.0.0.1")
port = int(os.environ.get("PORT", "8765"))
```

所以它可以适配 Render 提供的端口环境变量。

### 需要注意的一点

Render 会自动提供 `PORT` 环境变量。当前启动命令不需要硬编码端口，服务启动后会从环境中读取。

如果你未来想写得更明确，也可以使用：

```bash
cd ForecastDashboard && HOST=0.0.0.0 python server.py
```

当前代码会自动读取 Render 的 `PORT`，所以这个命令已经足够。

## 六、环境变量配置

在 Render 的 Environment 页面中添加变量。

建议至少配置：

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
```

如果你后续还要在 Render 上运行需要其他模型或接口的脚本，再补充：

```text
DASHSCOPE_API_KEY
SILICONFLOW_API_KEY
POWER_MARKET_AGENT_HOST
POWER_MARKET_AGENT_PORT
```

### 建议值

```text
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 原则

- 真实 key 只填在 Render 的环境变量里
- 不要写进 GitHub 代码
- 不要写进 `.env.example` 以外的本地配置文件

## 七、端口注意事项

我已经检查过当前后端代码，现有 `ForecastDashboard/server.py` **支持 Render 的 `PORT` 环境变量**，没有把端口写死成固定值。

当前代码会从环境变量读取：

- `HOST`
- `PORT`

所以这一项 **目前不需要额外改代码**。

如果你以后改动了服务入口，部署前要再确认一次有没有把 host/port 写死。

## 八、部署后验证

部署成功后，按下面顺序测试：

1. 打开 Render 提供的网址
2. 检查首页是否能访问
3. 访问 `/api/forecast?forecast_start=2026-05-01`
4. 访问 `/api/battery-strategy`
5. 如果你点击页面里的运行按钮，再测试 `/api/battery-strategy/run`
6. 确认返回 336 个预测点
7. 确认页面可以展示预测曲线

如果 `/api/forecast` 正常返回 JSON，说明后端基本工作正常。

## 九、常见问题

### 1. API Key 没配置

表现：

- 部分需要模型的功能报错
- 相关脚本无法调用外部模型服务

处理：

- 去 Render 的 Environment 页面补上对应 key

### 2. requirements 缺包

表现：

- Build 阶段失败
- 日志里提示 `ModuleNotFoundError`

处理：

- 检查 `requirements.txt`
- 确认依赖已经写全

### 3. 模型文件过大

表现：

- 上传 GitHub 很慢
- Render 构建时间长
- 甚至触发平台限制

处理：

- 只保留网页运行需要的模型文件
- 不要把大型训练中间文件都上传

### 4. 路径写死成本地路径

表现：

- 本机能跑
- Render 上找不到文件

处理：

- 用相对路径
- 避免写死 `/Users/...`

### 5. outputs 文件不存在

表现：

- Battery Strategy 区域显示空
- 页面提示找不到结果文件

处理：

- 先运行 `BatteryStrategy/run_battery_strategy.py`
- 确保输出目录存在

### 6. Render 免费服务冷启动

表现：

- 第一次打开较慢
- 一段时间没访问后再次进入会重新唤醒

处理：

- 这是免费服务的正常现象
- 不是程序错误

### 7. 端口绑定错误

表现：

- Render 显示服务启动失败
- 页面无法访问

处理：

- 确认后端使用 `HOST=0.0.0.0`
- 确认代码读取 `PORT` 环境变量

## 十、补充说明

当前项目已经有：

- `requirements.txt`
- `Procfile`
- `render.yaml`
- `ForecastDashboard/server.py`

因此部署准备已经基本完成。后续只需要：

1. 上传到 GitHub
2. 在 Render 创建 Web Service
3. 填好环境变量
4. 部署并验证

