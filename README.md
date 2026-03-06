# RAIDA (Telegram Edition)

RAIDA 是一个可远程控制开发机的 AI Agent 服务。现在默认前端入口是 **Telegram Bot**。

核心链路：

`Telegram -> Message Gateway -> Task Scheduler -> Executor Router -> Codex / Shell / Desktop -> Telegram`

---

## 你现在可以做到什么

在 Telegram 里直接发自然语言，例如：

- `打开 VSCode，进入 F:\OneDrive\desktop\项目\raida，帮我跑 pytest 并总结失败原因`
- `把当前分支推送到 GitHub，提交信息写 fix: improve startup` 
- `先帮我 git pull，再运行测试，失败就给我一个修复建议`

RAIDA 会创建任务、执行、持续回报进度，并把截图/日志文件回传到 Telegram。

---

## 架构目录

### `gateway/`
- `telegram_adapter.py`: Telegram 适配层（Webhook 入站 + Bot API 出站）
- `message_gateway.py`: 统一消息网关 (`receive_message`, `send_message`, `send_image`, `send_file`)

### `orchestrator/`
- `task_manager.py`: SQLite 任务状态 + 用户注册状态（`users` 表）
- `task_scheduler.py`: 后台调度与执行循环
- `context_store.py`: 任务上下文与产物持久化
- `reporter.py`: 执行状态回传

### `executors/`
- `code_executor.py`: Shell / Git / Tests / Codex 调用
- `desktop_executor.py`: 桌面自动化（截图、键鼠、窗口等）
- `executor_router.py`: 动作规划与路由

---

## 1. 安装

```bash
python --version
# 需要 3.11+
```

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

确保你本机有 `codex` 命令可用：

```bash
codex --help
```

---

## 2. 注册 Telegram Bot（必须）

### 2.1 在 Telegram 里找 `@BotFather`

1. 发送 `/newbot`
2. 输入 bot 名称（显示名）
3. 输入 bot 用户名（必须以 `bot` 结尾，例如 `raida_dev_bot`）
4. 获得 `BOT_TOKEN`（形如 `123456:ABC...`）

### 2.2（可选）设置命令菜单

在 `@BotFather` 执行 `/setcommands`，配置：

```text
start - onboarding
register - activate account
run - create task
pause - pause task
resume - resume task
cancel - cancel task
append - append instruction
tasks - list tasks
task - show task
```

### 2.3 获取你的 chat_id

先给 bot 发一条消息，然后执行：

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

在返回 JSON 中找到 `message.chat.id`，这就是你的 chat_id。

---

## 3. 环境变量配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RAIDA_HOST` | `0.0.0.0` | FastAPI 监听地址 |
| `RAIDA_PORT` | `8000` | FastAPI 端口 |
| `RAIDA_DB_PATH` | `data/raida.db` | SQLite 文件 |
| `RAIDA_TASK_DATA_DIR` | `data/tasks` | 任务产物目录 |
| `RAIDA_ALLOWED_WORKDIRS` | 当前目录 | 允许执行的工作目录（逗号分隔） |
| `RAIDA_CODEX_CLI_PATH` | `codex` | Codex CLI 路径 |
| `RAIDA_COMMAND_TIMEOUT` | `1800` | 命令超时秒数 |
| `RAIDA_LOG_LEVEL` | `INFO` | 日志级别 |
| `RAIDA_CONFIRM_NETWORK` | `true` | 网络命令需确认 |
| `RAIDA_CONFIRM_OVERWRITE` | `true` | 覆盖写入需确认 |
| `RAIDA_TELEGRAM_BOT_TOKEN` | 空 | Telegram Bot Token |
| `RAIDA_TELEGRAM_WEBHOOK_SECRET` | 空 | Telegram webhook secret_token |
| `RAIDA_TELEGRAM_WEBHOOK_PATH` | `/messages/telegram` | Telegram webhook 路径 |
| `RAIDA_TELEGRAM_ALLOWED_CHAT_IDS` | 空 | 允许使用的 chat_id 列表（逗号分隔） |
| `RAIDA_TELEGRAM_INVITE_CODE` | 空 | 注册邀请码（为空则 `/register` 无需参数） |
| `RAIDA_TELEGRAM_REQUIRE_REGISTRATION` | `true` | 是否要求先注册才能执行任务 |

PowerShell 示例：

```powershell
$env:RAIDA_TELEGRAM_BOT_TOKEN="<YOUR_BOT_TOKEN>"
$env:RAIDA_TELEGRAM_WEBHOOK_SECRET="<RANDOM_SECRET>"
$env:RAIDA_TELEGRAM_ALLOWED_CHAT_IDS="123456789"
$env:RAIDA_TELEGRAM_INVITE_CODE="raida-2026"
$env:RAIDA_ALLOWED_WORKDIRS="F:\OneDrive\desktop\项目\raida"
```

---

## 4. 启动服务

```bash
uvicorn raida.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
```

---

## 5. 配置 Telegram Webhook

假设你的公网 HTTPS 地址是：`https://your-domain.com`

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-domain.com/messages/telegram" \
  -d "secret_token=<YOUR_WEBHOOK_SECRET>"
```

检查是否生效：

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

> 注意：Telegram webhook 要求公网 HTTPS，内网地址不可直接用。

---

## 6. Telegram 内命令用法

先发：

- `/start`
- `/register <邀请码>`（如果你配置了邀请码）

然后可以直接发送：

- `/run 打开 VSCode 并在当前项目运行 pytest`
- `打开浏览器访问 github.com，然后截图`
- `/tasks`
- `/task <task_id>`
- `/pause <task_id>`
- `/resume <task_id>`
- `/cancel <task_id>`
- `/append <task_id> 先只修复环境问题`

高风险动作（如 `git push`、删除文件、外网访问）会进入 `waiting_confirmation`，你需要回复：

- `confirm`

---

## 7. 你提到的两个场景示例

### 7.1 打开 VSCode 并执行

Telegram 直接发：

```text
/run 打开 VSCode，进入 F:\OneDrive\desktop\项目\raida，帮我运行 pytest 并总结失败
```

### 7.2 推送代码到 GitHub

Telegram 直接发：

```text
/run 检查 git 状态，把当前改动提交，提交信息为 "fix: xxx"，然后 push 到 GitHub
```

注意事项：

- 你的机器上必须已经配置好 Git 认证（SSH key 或 PAT）
- `git push` 通常会触发安全确认，需回复 `confirm`

---

## 8. 本地调试入口

如果你暂时还没配置公网 webhook，可以用本地 mock 接口模拟：

```bash
curl -X POST http://127.0.0.1:8000/messages/telegram/mock \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tg_123456789","message":"/run 帮我执行 pytest -q"}'
```

---

## 9. 数据与状态

### 任务状态

- `pending`
- `running`
- `waiting_confirmation`
- `completed`
- `failed`
- `cancelled`

### 用户状态（新增）

- `pending`
- `active`
- `blocked`

任务产物目录：

`data/tasks/{task_id}/`

包含：

- `conversation.jsonl`
- `state.json`
- `logs/execution.log`
- `screenshots/`
- `patches/`

---

## 10. 安全建议（生产）

1. 强制设置 `RAIDA_TELEGRAM_WEBHOOK_SECRET`
2. 配置 `RAIDA_TELEGRAM_ALLOWED_CHAT_IDS`
3. 启用注册和邀请码
4. 严格限制 `RAIDA_ALLOWED_WORKDIRS`
5. 用低权限系统账号运行 RAIDA
6. 对外仅暴露 webhook 路由，结合 Nginx + HTTPS

---

## 11. 扩展模型后端

当前默认使用 `CodexBackend`，如需换模型：

1. 实现 `raida/agents/agent_backend.py` 的 `AgentBackend`
2. 在 `main.py` 注入你的 backend

调度层无需重写。
