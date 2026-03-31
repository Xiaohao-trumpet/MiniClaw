# MiniClaw

> 一个本地优先、可解释、可改造的个人 Agent Runtime。

MiniClaw 的目标不是“再做一个聊天机器人壳子”，而是把一个现代 Agent Runtime 的主链路真正做出来，并且让它对个人开发者足够透明、足够可控、足够容易修改。

---

## What MiniClaw Is

MiniClaw 是一个面向个人开发者的 Local-First Agent Runtime。

它现在已经不是单纯的“任务执行脚本”，而是一条完整的 runtime 主链路：

- `Interface Layer`：Telegram / HTTP / Mock 入口
- `Session & Task Management Layer`：session、task、上下文、状态持久化
- `Planning Layer`：自然语言到结构化 `ActionPlan`
- `Safety Layer`：统一 `allow / confirm / deny`
- `Execution / Feedback Layer`：结构化工具、本地执行、工件回传、最终答案输出

你可以把它理解为：

- 一个个人规模的 Agent Runtime
- 一个可以拆开学习的 Agent 工程样本
- 一个适合本地开发任务自动化的可控执行系统

---

## Implemented Features

下面这些能力已经在项目里实现，并且已经串成主链：

- 支持 Telegram Bot、HTTP API、Mock Telegram 三种入口
- 支持多 `session` 对话管理，可以创建、切换、查看当前会话
- 一个 session 下可以持续发起多个 task，并保留该 session 的对话上下文
- planner 会读取最近的 session conversation，而不是只看当前一句指令
- 支持 provider 抽象的模型层，不再绑定单一后端
- 当前支持两种模型接法：`codex_cli` 和 `openai_compatible`
- planner 输出采用严格 `ActionPlan` schema，并带归一化与 repair 机制
- 安全层已经统一成 `allow / confirm / deny`
- 对命令、写文件、URL、GUI 动作做结构化安全判断
- 支持高风险动作确认，不允许危险动作仅靠一次确认强行通过
- 执行层已经是 Linux-first，核心路径不依赖 Windows 特化命令
- 核心结构化工具已补齐：`find_files`、`search_text`、`read_multiple_files`、`get_system_info`
- 仍然支持 shell、文件、浏览器、截图、可选桌面能力
- 支持 `pause / resume / cancel / append / confirm`
- 所有任务会沉淀工件：`plan.json`、`execution_log.json`、`summary.txt`、`final_response.txt` 等
- 增加了 grouped intermediate output，中间过程会聚合成紧凑 progress
- 最终答案会和 planning / progress 分开发送
- 支持 `/details <task_id>`，按需展开查看完整 planning / execution 细节
- 旧的 task-only 数据会自动迁移到新的 session-aware 模型
- SQLite + 文件工件双持久化，方便复盘和调试

---

## Core Flow

MiniClaw 的核心流程可以概括成：

1. 用户通过 Telegram 或 HTTP 提交任务
2. 系统解析 active session，并创建 task
3. planner 基于当前指令和最近 session 对话生成 `ActionPlan`
4. safety guard 对每个 action 做 `allow / confirm / deny`
5. scheduler 将 action 路由给 executor 执行
6. 结果写入 SQLite 和 `data/tasks / data/sessions`
7. Telegram 收到一条 compact progress 更新
8. 最终答案单独发回用户

![flow](./flow.png)

---

## Quick Start

下面这套流程是“从零到跑通”的最短路径。

### 1. Create a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Choose Your Model Provider

MiniClaw 现在支持两种常用模式。

#### Option A: Codex CLI

如果你本机已经安装了 `codex` CLI，配置：

```bash
export SRC_MODEL_PROVIDER=codex_cli
export SRC_MODEL_NAME=codex
export SRC_CODEX_CLI_PATH=codex
export SRC_CODEX_SKIP_GIT_REPO_CHECK=true
export SRC_MODEL_TIMEOUT=1800
export SRC_MODEL_TEMPERATURE=0
```

#### Option B: OpenAI-Compatible API

如果你要接 OpenAI-compatible 服务，配置：

```bash
export SRC_MODEL_PROVIDER=openai_compatible
export SRC_MODEL_NAME=gpt-4.1-mini
export SRC_MODEL_API_BASE=https://your-api-base.example/v1
export SRC_MODEL_API_KEY=your_api_key
export SRC_MODEL_TIMEOUT=1800
export SRC_MODEL_TEMPERATURE=0
```

### 3. Configure Runtime Basics

最少还需要配置这些运行参数：

```bash
export SRC_ALLOWED_WORKDIRS=/home/yourname/code
export SRC_SESSION_RECENT_TURNS=12
export SRC_AUTO_CREATE_SESSION_ON_RUN=true
```

如果你要接 Telegram Bot，再配置：

```bash
export SRC_TELEGRAM_BOT_TOKEN=your_bot_token
export SRC_TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id
export SRC_TELEGRAM_REQUIRE_REGISTRATION=false
export SRC_TELEGRAM_POLL_TIMEOUT=30
export SRC_TELEGRAM_POLL_RETRY=3
```

如果你不配置 `SRC_TELEGRAM_BOT_TOKEN`，系统会自动退回 Mock Telegram 模式。

### 4. Start MiniClaw

推荐直接用项目自带脚本：

```bash
bash scripts/run_miniclaw.sh
```

如果你想手动启动：

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 5. Expected Startup Result

正常启动后，你应该看到类似日志：

- `TelegramBotApiAdapter started long polling.` 或 Mock adapter 提示
- `event=scheduler_started`
- `MiniClaw started on 0.0.0.0:8000 ...`

这表示：

- HTTP API 已经起来
- scheduler 已经开始工作
- Telegram polling 或 Mock 通道已经接好
- 模型 provider 已经初始化

### 6. First Telegram Commands

启动后，在 Telegram 私聊你的 bot：

```text
/start
/session new repo
/run summarize the current repository structure
```

然后你应该看到：

- 一条 task created 消息
- 一条会持续更新的 progress 消息
- 最后一条单独的 final answer

如果你想查看完整 planning / execution 细节：

```text
/details <task_id>
```

### 7. Quick Mock Test

如果你还没接 Telegram，可以先用 Mock 接口验证：

```bash
curl -X POST http://127.0.0.1:8000/messages/telegram/mock \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tg_123456789","message":"/run summarize the current repository structure"}'
```

### 8. Expected Runtime Artifacts

跑完一个任务后，应该能看到：

- `data/src.db`：SQLite 状态库
- `data/tasks/<task_id>/`：task 级执行工件
- `data/sessions/<session_id>/`：session 级对话上下文

典型工件包括：

- `planner_cleaned.txt`
- `execution_plan.json`
- `execution_log.json`
- `progress_details.txt`
- `summary.txt`
- `final_response.txt`

---

## Useful Commands

常用 Telegram 指令：

- `/run <instruction>`：创建新任务
- `/sessions`：列出自己的 sessions
- `/session`：查看当前 session
- `/session new [title]`：新建并切换 session
- `/session use <session_id>`：切换 active session
- `/session show [session_id]`：查看 session 详情
- `/task <task_id>`：查看某个 task 状态
- `/details <task_id>`：发送完整工件和详细日志
- `/append <task_id> <instruction>`：给已有 task 追加新指令
- `/pause <task_id>`：暂停
- `/resume <task_id>`：恢复
- `/cancel <task_id>`：取消
- `confirm` 或 `/confirm <task_id>`：确认高风险动作

---

## Architecture Snapshot

MiniClaw 现在最核心的设计，不是“一个 bot + 一堆命令”，而是：

- `session` 是对话与上下文单元
- `task` 是执行单元
- `action` 是 planner 生成的最小可执行动作

也就是说，它的主逻辑已经变成：

`User -> Session -> Task -> ActionPlan -> Safety -> Executor -> Progress -> Final Answer`

这也是它和简单聊天机器人或简单命令包装器的本质区别。

---

## MiniClaw vs OpenClaw

两者不是谁替代谁，而是目标不同。

### Feature and Logic Comparison

| 维度 | MiniClaw | OpenClaw |
|---|---|---|
| 核心单位 | `session -> task -> action` | 更偏 `agent -> session -> skills/tools -> execution host` |
| 规划方式 | 显式 `ActionPlan`，结构清晰，便于审计 | 更偏运行时 agent loop，平台化程度更高 |
| 安全逻辑 | runtime 内统一 `allow / confirm / deny` | 更强调宿主机侧 exec approvals 和 host policy |
| 执行方式 | 本地优先、单机可控、Linux-first | 更适合 gateway / node / 多宿主执行 |
| 输出逻辑 | grouped progress + separate final answer | 更偏事件流和平台化反馈 |
| 工程目标 | 可理解、可改造、可做个人实验 | 更成熟、更平台化、更面向复杂系统 |

### What OpenClaw Is Better For

OpenClaw 更适合：

- 想要更成熟、更完整的平台型 Agent 系统的人
- 需要多宿主、多节点、长期运行 agent 的团队
- 更看重产品化体验、生态和复杂部署能力的人
- 希望把 agent 作为一个平台能力来使用的人

### What MiniClaw Is Better For

MiniClaw 更适合：

- 个人开发者
- 想真正理解 Agent Runtime 架构的人
- 想在本地快速实验 planner / safety / executor / session 的人
- 需要一个可控、可改、可复盘的本地执行系统的人
- 做开发自动化、代码库分析、本地工具链集成实验的人

一句话总结：

- **OpenClaw 更像平台型 Agent 系统**
- **MiniClaw 更像面向个人开发者的可解释 Agent Runtime**

---

## Why This Project Matters

MiniClaw 的价值不只是“能不能跑任务”，而是：

- 让 Agent Runtime 的关键层次真正落地
- 让安全、规划、执行、反馈不再是抽象概念
- 让个人开发者也能拥有一个真正可控的本地 Agent 主链路

它不是为了炫技，而是为了把“现代 Agent 到底怎么工作”这件事，做成一个可以亲手理解和修改的工程系统。

---

## More Details

如果你想继续看更细的设计和完整使用说明，可以再读：

- [docs/05_user_manual.md](./docs/05_user_manual.md)
