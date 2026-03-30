# Safety Spec

## Goal
MiniClaw should default to non-destructive behavior. High-risk actions must be previewable, approvable, and auditable.

## Decision Model
- `allow`: safe to execute immediately inside the runtime.
- `confirm`: blocked until the user explicitly confirms.
- `deny`: hard refusal inside the runtime; confirmation cannot bypass it.

## Covered Actions
- `run_command`
- `write_file`
- `open_url`
- Desktop control actions such as `open_application`, `focus_window`, `type_text`, `press_key`, `mouse_click`
- Planner checkpoint action `request_confirmation`

## Hard Deny Scope
- Destructive system commands such as disk formatting or `rm -rf /`
- Shutdown or reboot commands
- Sensitive path writes such as `/etc`, `/proc`, `/sys`, `/root`, `.ssh`, and credential files
- Workspace-external file writes

## Confirmation Scope
- Dependency installation
- Network access
- Process management
- Existing file overwrite
- GUI control actions
- Planner-inserted confirmation checkpoints

## Runtime Guarantees
- Safety is enforced inside the scheduler before execution.
- Execution logs record safety decision, reason, preview, and category.
- Denied actions fail the task without execution.
- Confirmed actions can proceed only for the exact blocked cursor.

## Phase 1 Non-Goals
- Container isolation
- Policy-as-code editor UI
- Per-user policy customization
