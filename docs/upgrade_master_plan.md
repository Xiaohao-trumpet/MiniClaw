# Upgrade Master Plan

## Target State
MiniClaw should become:
- a safer personal agent runtime
- a model-provider-agnostic planner runtime
- Linux-first on the main execution path
- stronger for repository analysis and development workflows

## Dependency Order
1. Safety boundaries
2. Model abstraction
3. Linux-first execution refactor
4. Structured tooling expansion

## Phase 1 Delivered Shape
- Unified `allow/confirm/deny` safety decisions
- Provider factory with `codex_cli` and `openai_compatible`
- Core executor expanded with browser, screenshot, and structured repo tools
- Desktop executor reduced to optional GUI actions
- Planner prompt updated to prefer structured tools

## Still Out of Scope
- Strong sandbox isolation
- Mature GUI automation
- Production multi-tenant runtime
- Advanced multi-model routing
