# RAIDA (Telegram Long Polling Edition)

RAIDA controls your local developer machine through Telegram messages.

Core flow:

`Telegram -> Long Polling Adapter -> Message Gateway -> Task Scheduler -> Executors -> Telegram`

This edition uses **Telegram long polling only**. You do **not** need webhook, public IP, ngrok, or Cloudflare Tunnel.

## What You Can Do

Send natural language messages in Telegram, for example:

- `open VSCode, go to F:\OneDrive\desktop\项目\raida, run pytest and summarize failures`
- `check git status, commit with message "fix: startup", then push to GitHub`
- `pull latest changes, run tests, and only fix environment issues first`

RAIDA creates tasks, executes on your **local machine**, and sends progress/results back to Telegram.

## Architecture

### `gateway/`
- `telegram_adapter.py`: Telegram long polling + Bot API outbound (`sendMessage`, `sendPhoto`, `sendDocument`)
- `message_gateway.py`: Unified message gateway (`receive_message`, `send_message`, `send_image`, `send_file`)

### `orchestrator/`
- `task_manager.py`: SQLite tasks + users + runtime state (stores Telegram update offset)
- `task_scheduler.py`: Background scheduling/execution loop
- `context_store.py`: Task artifact persistence
- `reporter.py`: Outbound status/artifact reporting

### `executors/`
- `code_executor.py`: shell/git/tests/codex actions
- `desktop_executor.py`: deterministic desktop automation
- `executor_router.py`: action routing

## 1. Install

```bash
python --version
# Python 3.11+
```

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Make sure `codex` exists:

```bash
codex --help
```

## 2. Create Telegram Bot

1. Open Telegram and chat with `@BotFather`
2. Send `/newbot`
3. Set bot display name
4. Set bot username (must end with `bot`, e.g. `raida_dev_bot`)
5. Copy `BOT_TOKEN`

Optional command menu (`/setcommands` in BotFather):

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

## 3. Get Your Telegram chat_id

Use one of the methods below:

1. Message `@userinfobot` and read your id.
2. Or call Telegram API once before RAIDA starts:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

Find `message.chat.id`.

## 4. Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `RAIDA_HOST` | `0.0.0.0` | FastAPI host |
| `RAIDA_PORT` | `8000` | FastAPI port |
| `RAIDA_DB_PATH` | `data/raida.db` | SQLite database |
| `RAIDA_TASK_DATA_DIR` | `data/tasks` | Task artifact root |
| `RAIDA_ALLOWED_WORKDIRS` | current dir | Allowed execution roots |
| `RAIDA_CODEX_CLI_PATH` | `codex` | Codex CLI path |
| `RAIDA_COMMAND_TIMEOUT` | `1800` | Command timeout seconds |
| `RAIDA_LOG_LEVEL` | `INFO` | Log level |
| `RAIDA_CONFIRM_NETWORK` | `true` | Confirm network commands |
| `RAIDA_CONFIRM_OVERWRITE` | `true` | Confirm overwrite actions |
| `RAIDA_TELEGRAM_BOT_TOKEN` | empty | Telegram bot token |
| `RAIDA_TELEGRAM_ALLOWED_CHAT_IDS` | empty | Comma-separated allowed chat IDs |
| `RAIDA_TELEGRAM_INVITE_CODE` | empty | Registration invite code |
| `RAIDA_TELEGRAM_REQUIRE_REGISTRATION` | `true` | Require registration before running tasks |
| `RAIDA_TELEGRAM_POLL_TIMEOUT` | `30` | `getUpdates` long poll timeout |
| `RAIDA_TELEGRAM_POLL_RETRY` | `3` | Retry interval on polling failures |

PowerShell example:

```powershell
cd "F:\OneDrive\desktop\项目\raida"

$env:RAIDA_TELEGRAM_BOT_TOKEN="<YOUR_BOT_TOKEN>"
$env:RAIDA_TELEGRAM_ALLOWED_CHAT_IDS="123456789"
$env:RAIDA_TELEGRAM_INVITE_CODE="raida-2026"
$env:RAIDA_TELEGRAM_REQUIRE_REGISTRATION="true"
$env:RAIDA_ALLOWED_WORKDIRS="F:\OneDrive\desktop\项目\raida"
$env:RAIDA_TELEGRAM_POLL_TIMEOUT="30"
$env:RAIDA_TELEGRAM_POLL_RETRY="3"
```

## 5. Start Service

```bash
uvicorn raida.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

Once started, RAIDA automatically:

1. Tries to disable Telegram webhook (`deleteWebhook`) to avoid mode conflict.
2. Starts long polling (`getUpdates`) in a background thread.
3. Stores latest update offset in SQLite runtime state.

## 6. Telegram Commands

Send these to your bot:

- `/start`
- `/register <invite_code>` (if invite code enabled)
- `/run <instruction>`
- `/tasks`
- `/task <task_id>`
- `/pause <task_id>`
- `/resume <task_id>`
- `/cancel <task_id>`
- `/append <task_id> <instruction>`
- `confirm` (for risky actions)

You can also send plain text without `/run`; it is treated as a task instruction.

## 7. Examples You Asked For

### 7.1 Open VSCode and run tests

```text
/run open VSCode, enter F:\OneDrive\desktop\项目\raida, run pytest and summarize failures
```

### 7.2 Push code to GitHub

```text
/run check git status, commit current changes with message "fix: xxx", then push to GitHub
```

Notes:

- Local machine must already have Git auth configured (SSH key or PAT).
- `git push` usually triggers safety confirmation; reply `confirm`.

## 8. Local Debug Endpoint (No Telegram Network)

```bash
curl -X POST http://127.0.0.1:8000/messages/telegram/mock \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tg_123456789","message":"/run run pytest -q"}'
```

## 9. Persistence

Task statuses:

- `pending`
- `running`
- `waiting_confirmation`
- `completed`
- `failed`
- `cancelled`

User statuses:

- `pending`
- `active`
- `blocked`

Task artifact directory:

`data/tasks/{task_id}/`

Contains:

- `conversation.jsonl`
- `state.json`
- `logs/execution.log`
- `screenshots/`
- `patches/`

## 10. Security Recommendations

1. Set `RAIDA_TELEGRAM_ALLOWED_CHAT_IDS`.
2. Keep registration enabled and use invite code.
3. Restrict `RAIDA_ALLOWED_WORKDIRS`.
4. Run RAIDA with low OS privileges.
5. Keep risky-action confirmation enabled.

## 11. Model Backend Extension

Current default backend is `CodexBackend`.

To add another model backend:

1. Implement `AgentBackend` in `raida/agents/agent_backend.py`
2. Inject it in `raida/main.py`

Scheduler and executor layers do not need rewriting.
