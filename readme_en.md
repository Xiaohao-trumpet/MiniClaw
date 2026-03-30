# MiniClaw

MiniClaw is a local-first remote developer agent controlled from Telegram.

## Why This Refactor

Old behavior:
- Codex CLI was called too directly.
- If Codex sandbox/session could not execute locally, the system often returned suggestions.
- Tasks could appear successful even when nothing executed on the host machine.

New behavior:
- **Codex plans**
- **Python executes locally**
- **Safety Guard approves risky actions**
- **Telegram reports real execution results**

No action is reported as successful unless the Python executor actually ran it.

## Core Architecture

Flow:

`Instruction -> Planner -> Structured ActionPlan -> Safety Guard -> Executor Router -> Local Executors -> Artifacts -> Telegram`

Main modules:
- `src/planner/`
  - `action_models.py`: strict Pydantic schema for `ActionPlan` and `PlannedAction`
  - `plan_parser.py`: robust JSON extraction/validation
  - `codex_planner.py`: Codex CLI planner wrapper (JSON-only contract)
- `src/executors/`
  - `system_executor.py`: `run_command`, `list_directory`, `read_file`, `write_file`, `respond_only`
  - `desktop_executor.py`: `open_application`, `open_url`, `take_screenshot`, desktop actions
  - `executor_router.py`: dispatch layer
- `src/safety/safety_guard.py`: high-risk detection and confirmation gating
- `src/orchestrator/task_scheduler.py`: planning/execution lifecycle + resume logic
- `src/orchestrator/context_store.py`: task artifact persistence
- `prompts/action_planner.md`: planner contract prompt file

## Task Lifecycle

Task statuses:
- `pending`
- `planning`
- `awaiting_confirmation`
- `running`
- `completed`
- `failed`
- `cancelled`

Lifecycle diagram:

`pending -> planning -> running -> completed`

`planning -> failed` (plan parse/validation/backend failure)

`running -> awaiting_confirmation -> pending -> running` (after `confirm` or `/confirm <task_id>`)

`running -> failed|cancelled`

## Action Schema

Each action has:
- `action_type`
- `args`
- `reason`
- `risk_level` (`low|medium|high|critical`)
- `requires_confirmation`

Supported action types:
- `run_command`
- `open_application`
- `open_url`
- `list_directory`
- `read_file`
- `write_file`
- `take_screenshot`
- `focus_window`
- `type_text`
- `press_key`
- `mouse_click`
- `request_confirmation`
- `respond_only`

## Confirmation Flow

Safety guard blocks risky actions before execution (for example `git push`, package installs, destructive shell commands).

When blocked:
1. Task enters `awaiting_confirmation`
2. Telegram receives reason and confirmation instruction
3. User replies `confirm` or `/confirm <task_id>`
4. Scheduler resumes from blocked cursor and continues execution

## Artifacts

Per-task directory:

`data/tasks/{task_id}/`

Common artifacts:
- `plan.json`
- `execution_log.json`
- `stdout.txt`
- `stderr.txt`
- `summary.txt`
- `planner_raw_output.txt`
- `logs/execution.log`
- `screenshots/`
- `patches/`

`execution_log.json` records each action with explicit status:
- `executed`
- `blocked`
- `failed`
- `skipped`

## Planner Prompt Contract

Prompt template file:
- `prompts/action_planner.md`

Planner rules:
- planner only, not executor
- valid JSON object only
- no hallucinated execution claims
- low-risk first
- mark risky actions with confirmation requirements

## Example

Instruction:

`/run open VS Code and show what we have in the folder`

Expected behavior:
1. `task created`
2. `planning started`
3. `plan accepted`
4. `open_application(vscode)` executes locally
5. `list_directory(path=...)` executes locally
6. Telegram gets real action results and final summary from executor outputs

Incorrect legacy behavior (now removed):
- Codex suggests commands like `code .` and `Get-ChildItem` without local execution
- Task marked complete anyway

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SRC_DB_PATH` | `data/src.db` | SQLite database |
| `SRC_TASK_DATA_DIR` | `data/tasks` | Task artifact root |
| `SRC_ALLOWED_WORKDIRS` | current dir | Allowed execution roots |
| `SRC_CODEX_CLI_PATH` | `codex` | Codex CLI path |
| `SRC_PLANNER_PROMPT_FILE` | `prompts/action_planner.md` | Planner prompt template |
| `SRC_COMMAND_TIMEOUT` | `1800` | Command timeout seconds |
| `SRC_TELEGRAM_BOT_TOKEN` | empty | Telegram bot token |
| `SRC_TELEGRAM_ALLOWED_CHAT_IDS` | empty | Allowed Telegram IDs |

## Run

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Mock Telegram test:

```bash
curl -X POST http://127.0.0.1:8000/messages/telegram/mock \
  -H "Content-Type: application/json" \
  -d '{"user_id":"tg_123456789","message":"/run open VS Code and show files in ."}'
```
