# Tooling Spec

## Goal
Reduce planner dependence on fragile shell commands by adding structured tools first.

## Phase 1 Tools
- `find_files`
- `search_text`
- `read_multiple_files`
- `get_system_info`

## Tool Output Rules
- Outputs should be readable in Telegram-style message channels.
- Tools should return structured metadata that can be reused by logs and summaries.
- Tool results should prefer concise previews over raw shell-style dumps.

## Planning Policy
- Prefer structured tools over `run_command` when they can answer the task.
- Use shell only when structured tools are insufficient.
- Codebase analysis should usually begin with discovery and read tools.

## Future Tool Candidates
- Git status and diff preview
- Patch application
- Test run wrapper
- Service status inspection
