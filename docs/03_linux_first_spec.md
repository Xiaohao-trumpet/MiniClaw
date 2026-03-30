# Linux-First Spec

## Goal
Keep MiniClaw's main path reliable on Linux, usable on macOS, and minimally compatible on Windows.

## Capability Split
### Core execution
- Shell command execution
- Filesystem read/write
- File discovery and text search
- Browser open
- Screenshot capture

### Optional desktop execution
- Open applications
- Focus windows
- Type text
- Press keys
- Mouse clicks

## Platform Policy
- Core actions should not depend on Windows-only commands.
- `open_application` must dispatch by platform.
- GUI automation is treated as optional and higher risk.

## Current Implementation Direction
- `open_url` and `take_screenshot` live in the core executor.
- Desktop executor no longer assumes `cmd /c start` for every path.
- Shell runner accepts a configurable shell executable.
