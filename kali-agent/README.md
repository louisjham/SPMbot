# Kali Agent

Autonomous AI agent daemon for Kali Linux, controlled via Telegram, powered by tool-using LLM.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           KALI AGENT ARCHITECTURE                        │
└─────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────┐
                              │   Telegram   │
                              │    Client    │
                              └──────┬───────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         Telegram Bot Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ /start      │  │ /status     │  │ /history    │  │ /cancel      │  │
│  │ /help       │  │ /clear      │  │ /scan       │  │ /fuzz ...    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────┘  │
│                                                                         │
│                    bot/commands.py • bot/telegram.py                    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           Agent Loop                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  1. Receive message  →  2. Build context  →  3. Call LLM        │   │
│  │  4. Parse response   →  5. Execute tool   →  6. Check stops     │   │
│  │  7. Loop or return  ←───────────────────────────────────────────┘   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│                    agent/loop.py • agent/conditions.py                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
┌──────────────────────────────┐   ┌──────────────────────────────────────┐
│       LLM Client             │   │         Skill Registry               │
│  ┌────────────────────┐      │   │  ┌────────────────────────────────┐  │
│  │ OpenAI-compatible  │      │   │  │     Python Skills              │  │
│  │ API (z.ai/GPT-4)   │      │   │  │  • nmap_scan   • gobuster_enum │  │
│  └────────────────────┘      │   │  │  • nuclei_scan • web_recon     │  │
│                              │   │  └────────────────────────────────┘  │
│       agent/llm.py           │   │  ┌────────────────────────────────┐  │
│                              │   │  │     YAML Skills                │  │
│                              │   │  │  • nikto_scan  • ffuf_fuzz     │  │
│                              │   │  │  • sqlmap_scan • subfinder     │  │
│                              │   │  │  • whatweb     • feroxbuster   │  │
│                              │   │  └────────────────────────────────┘  │
│                              │   │                                      │
│                              │   │  skills/registry.py • yaml_loader.py │
└──────────────────────────────┘   └──────────────────────────────────────┘
                          │                     │
                          └──────────┬──────────┘
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Context & Storage                                │
│  ┌─────────────────────┐          ┌─────────────────────────────┐      │
│  │  Context Manager    │          │     SQLite Store            │      │
│  │  • Message history  │          │  • Task persistence         │      │
│  │  • Session state    │          │  • Conversation logs        │      │
│  └─────────────────────┘          └─────────────────────────────┘      │
│                                                                         │
│              agent/context.py              store/sqlite.py              │
└────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Kali Linux Tools                                   │
│   nmap • nikto • ffuf • sqlmap • nuclei • gobuster • subfinder • ...   │
└────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Autonomous Pentest Workflows** - Agent iteratively plans and executes security assessments
- **Telegram Control** - Full bot interface with real-time status updates
- **Dynamic Skills** - Extend via Python classes or YAML definitions
- **Confirmation Gates** - Dangerous operations require explicit approval
- **Context Management** - Maintains conversation history and task state
- **YAML Skill Definitions** - Add new tools without writing code

## Requirements

| Requirement | Notes |
|-------------|-------|
| Kali Linux | WSL supported |
| Python 3.12+ | Required for modern async features |
| Telegram Bot Token | From [@BotFather](https://t.me/BotFather) |
| z.ai API Key | Or any OpenAI-compatible API |

## Quick Start

### 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/yourorg/kali-agent.git
cd kali-agent

# Run the installer (requires sudo)
sudo ./install.sh
```

### 2. Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit with your credentials
nano .env
```

```env
# .env
ZAI_API_KEY=your_api_key_here
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### 3. Configure Allowed Users

Edit `config/settings.yaml` to add your Telegram user ID:

```yaml
telegram:
  allowed_users:
    - 123456789  # Your Telegram user ID
```

### 4. Start the Service

```bash
# Enable and start via systemd
sudo systemctl enable kali-agent
sudo systemctl start kali-agent

# Or run directly
python daemon.py
```

### 5. Verify Installation

```bash
# Check service status
sudo systemctl status kali-agent

# View logs
journalctl -u kali-agent -f
```

## Usage

### Basic Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize conversation and show welcome |
| `/help` | Display available commands |
| `/status` | Show current agent and task status |
| `/cancel` | Cancel running operation |
| `/history` | View conversation history |
| `/clear` | Clear conversation context |

### Skill Commands (Slash Shortcuts)

| Command | Tool | Description |
|---------|------|-------------|
| `/scan <target>` | nmap | Quick network scan |
| `/nikto <target>` | nikto | Web vulnerability scan |
| `/whatweb <url>` | whatweb | Technology fingerprinting |
| `/fuzz <url>` | ffuf | Web path fuzzing |
| `/sqlmap <url>` | sqlmap | SQL injection testing |
| `/subs <domain>` | subfinder | Subdomain enumeration |
| `/ferox <url>` | feroxbuster | Directory brute-forcing |

### Example Sessions

**Network Reconnaissance:**

```
You: Scan 192.168.1.0/24 for live hosts

Agent: I'll perform a quick network discovery scan.
[Executing: nmap -sn 192.168.1.0/24]

Found 12 live hosts:
• 192.168.1.1 (gateway)
• 192.168.1.10 (web server)
• 192.168.1.50 (workstation)
...
```

**Web Assessment:**

```
You: Check https://example.com for vulnerabilities

Agent: I'll run multiple reconnaissance tools. Starting with:
[Executing: whatweb https://example.com]
[Executing: nikto -h https://example.com]

Results:
• Server: nginx/1.18.0
• Technologies: PHP 8.1, MySQL
• Potential XSS in /search?q= parameter
• Missing security headers (X-Frame-Options)
...
```

**Interactive Exploitation:**

```
You: Test for SQL injection on the login form

Agent: I'll use sqlmap to test the login endpoint.
⚠️ This is a potentially dangerous operation. Confirm? [y/N]

You: y

Agent: [Executing: sqlmap -u https://example.com/login --batch]

SQL injection found in 'username' parameter (POST).
Type: time-based blind
Payload: ' OR SLEEP(5)--
```

## Adding Skills

### Method 1: Python Class

Create a new file in `skills/` directory:

```python
# skills/my_scan.py
"""Custom scanning skill example."""

import asyncio
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter


class MyScan(Skill):
    """Custom network scanning skill."""
    
    name: str = "my_scan"
    description: str = "Perform custom network reconnaissance"
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="target",
            type="string",
            description="Target hostname or IP",
            required=True,
        ),
        ToolParameter(
            name="intensity",
            type="string",
            description="Scan intensity level",
            required=False,
            enum=["light", "medium", "aggressive"],
        ),
    ]
    dangerous: bool = False
    timeout: int = 300
    slash_command: str | None = "/myscan"
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the custom scan."""
        target = kwargs.get("target")
        intensity = kwargs.get("intensity", "medium")
        
        # Build and execute command
        cmd = f"my-tool -t {target} -i {intensity}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        
        return SkillResult(
            success=proc.returncode == 0,
            output=stdout.decode() if stdout else stderr.decode(),
            artifacts=["/tmp/my_scan_output.txt"],
        )
```

Register in `skills/__init__.py`:

```python
from skills.my_scan import MyScan

__all__ = ["NmapScan", "MyScan", ...]
```

### Method 2: YAML Definition

Add to `config/skills.yaml`:

```yaml
quick_skills:
  # Custom DNS enumeration
  dnsrecon_enum:
    name: dnsrecon_enum
    description: DNS reconnaissance and zone transfer attempts
    slash_command: /dnsrecon
    command_template: dnsrecon -d {domain} -t {scan_type:std} -o /tmp/dnsrecon_last.txt
    dangerous: false
    timeout: 300
    parameters:
      - name: domain
        type: string
        description: Target domain to enumerate
        required: true
      - name: scan_type
        type: string
        description: Scan type (std, rvl, brt, srv, axfr)
        required: false
        enum: [std, rvl, brt, srv, axfr]

  # Custom SMB enumeration
  smb_enum:
    name: smb_enum
    description: Enumerate SMB shares and users
    slash_command: /smb
    command_template: enum4linux -a {target} > /tmp/smb_enum.txt
    dangerous: true
    timeout: 600
    parameters:
      - name: target
        type: string
        description: Target IP or hostname
        required: true
```

**YAML Skill Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✓ | Unique skill identifier |
| `description` | string | ✓ | What the skill does |
| `slash_command` | string | | Telegram shortcut (e.g., `/scan`) |
| `command_template` | string | ✓ | Command with `{param}` placeholders |
| `dangerous` | bool | | Requires confirmation (default: false) |
| `timeout` | int | | Max execution time in seconds |
| `parameters` | list | | Parameter definitions |

**Parameter Definition:**

```yaml
parameters:
  - name: url           # Parameter name (used in template)
    type: string        # string, integer, boolean
    description: Target URL
    required: true
    enum: [val1, val2]  # Optional: allowed values
```

**Template Syntax:**

```yaml
# {param} - required parameter
# {param:default} - parameter with default value
command_template: tool -t {target} -m {mode:fast} -o /tmp/output.txt
```

## Configuration

### settings.yaml

```yaml
# LLM Configuration
llm:
  base_url: "https://api.openai.com/v1"
  api_key: "${ZAI_API_KEY}"      # From environment variable
  model: "gpt-4"

# Telegram Bot Configuration  
telegram:
  token: "${TELEGRAM_BOT_TOKEN}"  # From environment variable
  allowed_users:
    - 123456789                    # List of allowed Telegram user IDs

# Agent Configuration
agent:
  max_iterations: 10              # Max agent loop iterations
  default_timeout: 300            # Default skill timeout (seconds)
  confirm_dangerous: true         # Require confirmation for dangerous ops

# Data Store Configuration
store:
  sqlite_path: "./data/kali_agent.db"
```

### Environment Variables (.env)

```env
# Required
ZAI_API_KEY=sk-xxx                 # LLM API key
TELEGRAM_BOT_TOKEN=123xxx:yyy      # Bot token from @BotFather
```

### Finding Your Telegram User ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your user ID
3. Add this ID to `allowed_users` in settings.yaml

## Security Considerations

⚠️ **WARNING: This tool performs actual security testing. Use responsibly.**

### Authentication

- Only whitelisted Telegram users can interact with the agent
- User IDs are verified on every message
- Keep `.env` file secure and never commit it

### Scope Limiting

- Define clear rules in `config/prompts/system.md`
- Use `confirm_dangerous: true` to gate risky operations
- Review skill `dangerous` flags before deployment

### Best Practices

1. **Authorization** - Only test systems you own or have permission to test
2. **Scope** - Define explicit targets and boundaries in system prompts
3. **Monitoring** - Review logs regularly via `journalctl -u kali-agent`
4. **Updates** - Keep Kali tools updated: `sudo apt update && sudo apt upgrade`
5. **Network** - Consider running in isolated network segments

### Legal Notice

```
This tool is intended for authorized security testing only.
Unauthorized access to computer systems is illegal.
Users are responsible for ensuring compliance with applicable laws.
The developers assume no liability for misuse.
```

## Troubleshooting

### Service won't start

```bash
# Check logs
journalctl -u kali-agent -n 50

# Verify environment
cat /opt/kali-agent/.env

# Test manually
cd /opt/kali-agent
source .venv/bin/activate
python daemon.py
```

### Telegram bot not responding

```bash
# Verify token is valid
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"

# Check allowed_users contains your ID
grep allowed_users /opt/kali-agent/config/settings.yaml
```

### Skills failing

```bash
# Verify tools are installed
which nmap nikto ffuf sqlmap

# Install missing tools
sudo apt install nmap nikto ffuf sqlmap
```

## License

MIT License

```
Copyright (c) 2024 Kali Agent Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
