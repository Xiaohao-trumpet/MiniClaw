# Model Abstraction Spec

## Goal
Replace the Codex-specific backend contract with a provider-agnostic model layer.

## Core Abstractions
- `ModelAdapter`: provider interface.
- `ModelRequest`: normalized input with `prompt`, `system_prompt`, `options`, and provider metadata.
- `ModelResponse`: normalized output with `text`, `raw_payload`, `usage`, `finish_reason`, `provider`, and `model`.
- `GenerationOptions`: shared generation controls.

## Provider Targets
- `codex_cli`
- `openai_compatible`

## Configuration
`Settings.model` contains:
- `provider`
- `model_name`
- `api_base`
- `api_key`
- `timeout_seconds`
- `temperature`
- `codex_cli_path`
- `codex_skip_git_repo_check`

## Runtime Rules
- Planner consumes only normalized model text.
- Provider and model are logged on planner requests and accepted plans.
- Switching provider should require config changes only.

## Phase 1 Non-Goals
- Multi-model routing
- Automatic fallback across providers
- Provider-specific prompt branching inside planner logic
