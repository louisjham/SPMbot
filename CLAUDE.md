# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kali Agent is an autonomous AI security testing assistant running on Kali Linux, controlled via Telegram, powered by a tool-using LLM. The agent iteratively plans and executes security assessments using a registry of skills that wrap common security tools (nmap, gobuster, nuclei, etc.).

## Common Commands

### Installation and Setup
```bash
# Install the agent (requires sudo, interactive)
cd kali-agent
sudo ./install.sh

# Manual setup after installation
source .venv/bin/activate  # Activate virtual environment
```

### Running the Service
```bash
# Start via systemd
sudo systemctl start kali-agent
sudo systemctl enable kali-agent  # Enable on boot

# Run directly (for development/testing)
cd kali-agent
source .venv/bin/activate
python daemon.py

# Check service status
sudo systemctl status kali-agent

# View logs
journalctl -u kali-agent -f
```

### Testing
```bash
# Run all tests
cd kali-agent
pytest tests/

# Run specific test file
pytest tests/test_store_findings.py

# Run with verbose output
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=.
```

### Development
```bash
# Install dependencies
cd kali-agent
source .venv/bin/activate
pip install -r requirements.txt

# Add new security tools (via apt)
sudo apt install nmap gobuster nuclei nikto sqlmap subfinder feroxbuster whatweb ffuf
```

## Architecture

### Core Components

**daemon.py** - Main entry point that orchestrates all components:
- Loads environment variables and YAML configuration
- Initializes LLM client, skill registry, context manager, agent loop, and Telegram bot
- Wires callbacks between agent and bot
- Handles graceful shutdown

**agent/loop.py** - AgentLoop class that executes the main reasoning loop:
- Iterates up to max_iterations calling LLM and executing skills
- Manages task state (RUNNING, COMPLETED, STOPPED, FAILED)
- Handles dangerous skill confirmation via callbacks
- Checks stop conditions after each iteration
- Compresses context when needed

**agent/llm.py** - LLMClient for OpenAI-compatible APIs:
- Handles chat completion with function calling
- Supports any OpenAI-compatible endpoint (configured in settings.yaml)

**skills/registry.py** - SkillRegistry for skill management:
- Auto-discovers Python skills from `skills/` package
- Registers skills with optional slash command mapping
- Converts skills to OpenAI tool schema format
- Supports YAML-based skill definitions

**skills/base.py** - Base classes:
- `Skill` abstract base class - all skills inherit from this
- `ToolParameter` - defines skill parameters with JSON Schema types
- `SkillResult` - standard result format with success, output, artifacts

**bot/telegram.py** - TelegramInterface:
- Handles Telegram bot events (messages, commands)
- Maps slash commands to skills
- Implements user authentication via allowed_users whitelist
- Provides status and confirmation callbacks to agent loop

**store/sqlite.py** - SQLiteStore for persistence:
- Stores tasks, conversations, and findings
- Async database operations using aiosqlite

### Skill System

The agent can use two types of skills:

**1. Python Skills** (in `skills/` directory):
- Inherit from `Skill` base class
- Define `name`, `description`, `parameters`, `dangerous`, `timeout`, `slash_command`
- Implement `async execute(**kwargs) -> SkillResult` method
- Auto-discovered via `SkillRegistry.auto_discover("skills")`

**2. YAML Skills** (defined in `config/skills.yaml`):
- Define skills declaratively with `command_template` and parameters
- Loaded via `load_yaml_skills(skills, path)` in daemon.py
- Template syntax: `{param}` for required, `{param:default}` for optional

### Configuration Flow

1. **Environment** (.env) - Sensitive values: `ZAI_API_KEY`, `TELEGRAM_BOT_TOKEN`
2. **Settings** (config/settings.yaml) - App configuration with `${VAR}` expansion:
   - `llm`: API endpoint, model, base_url
   - `telegram`: bot token, allowed_users whitelist
   - `agent`: max_iterations, default_timeout, confirm_dangerous
   - `store`: sqlite_path
3. **Skills** (config/skills.yaml) - YAML skill definitions

### Message Flow

```
Telegram Message → Bot Interface → Agent Loop → LLM
                                                    ↓
User ← Bot Interface ← Agent Loop ← Skills ← Tools (nmap, etc.)
```

## Important Implementation Details

### Skill Execution Order
1. Agent receives user message
2. AgentLoop calls LLM with available tools (from SkillRegistry.all_tools())
3. LLM responds with tool_calls
4. For each tool_call:
   - Lookup skill by name in registry
   - Check if dangerous → call confirm_callback if needed
   - Execute skill.execute(**arguments)
   - Append tool result to conversation
5. Check stop conditions
6. Repeat until completion or max_iterations

### Context Management
- Conversation history stored in `AgentTask.messages`
- ContextManager can compress long conversations
- System prompt updated each iteration with current iteration count

### Async Architecture
- All I/O operations are async (database, HTTP, subprocess)
- Use `asyncio.create_subprocess_shell` for tool execution
- AgentLoop.run() runs tasks asynchronously

### Security Model
- Only whitelisted Telegram user IDs can interact (settings.yaml: telegram.allowed_users)
- Dangerous skills require user confirmation before execution
- Sensitive credentials in .env file (never committed)

## File Structure Reference

```
kali-agent/
├── daemon.py              # Main entry point
├── requirements.txt       # Python dependencies
├── install.sh            # Installation script
├── .env                  # Environment variables (create from .env.example)
├── config/
│   ├── settings.yaml     # App configuration
│   ├── skills.yaml       # YAML skill definitions
│   └── prompts/
│       └── system.md     # System prompt for LLM
├── agent/
│   ├── loop.py          # AgentLoop - main execution loop
│   ├── llm.py           # LLMClient - API wrapper
│   ├── context.py       # ContextManager - conversation state
│   └── conditions.py    # Stop condition checking
├── skills/
│   ├── base.py          # Skill base class
│   ├── registry.py      # SkillRegistry
│   ├── yaml_loader.py   # YAML skill loader
│   ├── nmap_scan.py     # Example skill
│   ├── gobuster_enum.py
│   ├── nuclei_scan.py
│   └── web_recon.py
├── bot/
│   ├── telegram.py      # TelegramInterface
│   ├── commands.py      # Command handlers
│   └── formatters.py    # Message formatting
├── tasks/
│   ├── models.py        # AgentTask, TaskConfig, TaskState
│   └── manager.py       # TaskManager
├── store/
│   └── sqlite.py        # SQLiteStore
└── tests/
    ├── conftest.py      # Pytest configuration (sets Python path)
    └── test_*.py        # Test files
```

## Adding New Features

### Adding a Python Skill
1. Create `skills/my_tool.py` with class inheriting from `Skill`
2. Define parameters with ToolParameter
3. Implement `async execute(**kwargs) -> SkillResult`
4. Skill is auto-discovered on next daemon start

### Adding a YAML Skill
1. Add entry to `config/skills.yaml`
2. Define name, description, command_template, parameters
3. Skills are loaded on daemon startup via `load_yaml_skills()`

### Adding New Telegram Commands
1. Add command handler in `bot/commands.py`
2. Register handler in `TelegramInterface` initialization
3. Use `agent_loop.run()` to execute tasks

## Testing Notes

- Tests must import from `kali-agent` directory
- `conftest.py` adds kali-agent to sys.path
- Use pytest fixtures for database and component setup
- Mock external tool calls in unit tests
- Integration tests should test full agent loops with real components

## Dependencies

Python packages (requirements.txt):
- `aiogram>=3.4` - Telegram bot framework
- `openai>=1.30` - OpenAI API client
- `aiosqlite` - Async SQLite
- `pyyaml` - YAML configuration
- `pydantic` - Data validation
- `python-dotenv` - Environment variables

System packages (installed via install.sh):
- nmap, gobuster, nuclei, nikto, sqlmap, subfinder, feroxbuster, whatweb, ffuf
- redis-server (if needed)
- python3-venv, python3-full
