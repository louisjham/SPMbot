# Project Rules

## Code Location

**All code for this project must always be placed in the `c:\antigravity\SPMbot` directory.**

This is the designated workspace directory for the kali-agent project. No files should be created outside of this directory structure.

## Directory Structure

```
c:\antigravity\SPMbot\
├── daemon.py              # Main entry point
├── config/                # Configuration files
│   ├── settings.yaml
│   ├── skills.yaml
│   └── prompts/
├── agent/                 # Core agent logic
├── skills/                # Skill implementations
├── bot/                   # Telegram bot integration
├── tasks/                 # Task management
├── store/                 # Data persistence
└── rules/                 # Project rules (this file)
```

## Guidelines

1. All new modules and packages must be created within this directory
2. Configuration files must reference paths relative to this directory
3. Tests should be placed in a `tests/` subdirectory within this project
4. Any temporary files or caches should be placed in a `.tmp/` or `.cache/` subdirectory
