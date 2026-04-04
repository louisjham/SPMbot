#!/usr/bin/env python3
"""
Kali Agent Daemon - Main entry point for the AI-powered security assistant.

This module initializes and runs the Kali Agent service, coordinating
between the Telegram bot interface and the underlying agent logic.
"""

import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.llm import LLMClient
from agent.loop import AgentLoop
from bot.telegram import TelegramInterface
from skills.registry import SkillRegistry
from skills.yaml_loader import load_yaml_skills
from store.sqlite import SQLiteStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def expand_env_vars(obj: Any) -> Any:
    """
    Recursively expand environment variables in configuration values.
    
    Replaces ${ENV_VAR} placeholders with values from os.environ.
    If an environment variable is not set, the placeholder is left unchanged.
    
    Args:
        obj: Configuration object (dict, list, str, or other).
    
    Returns:
        The configuration object with environment variables expanded.
    """
    if isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        # Replace ${VAR_NAME} patterns with environment variable values
        def replace_env_var(match: re.Match[str]) -> str:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is not None:
                return value
            # Return original placeholder if env var not found
            return match.group(0)
        
        return re.sub(r'\$\{(\w+)\}', replace_env_var, obj)
    return obj


def load_settings() -> dict[str, Any]:
    """
    Load settings from YAML configuration file.
    
    Environment variables in the config are expanded using ${ENV_VAR} syntax.
    
    Returns:
        dict: Application settings dictionary.
    """
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    
    if not config_path.exists():
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return {}
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    
    # Expand environment variables in string values
    config_data = expand_env_vars(config_data)
    logger.info(f"Loaded configuration from {config_path}")
    
    return config_data or {}


async def main() -> None:
    """
    Main entry point for the Kali Agent daemon.
    
    Initializes all components in the correct order:
    1. Loads environment variables and settings
    2. Initializes LLM client
    3. Initializes skill registry and discovers skills
    4. Initializes context manager
    5. Initializes agent loop
    6. Initializes store
    7. Initializes Telegram bot interface
    8. Wires callbacks and signal handlers
    9. Starts the bot
    """
    # 1. Load environment variables from .env file
    load_dotenv(PROJECT_ROOT / ".env")
    logger.info("Loaded environment variables from .env file")
    
    # 2. Load settings from YAML configuration
    settings = load_settings()
    
    # Extract configuration sections
    llm_config = settings.get("llm", {})
    telegram_config = settings.get("telegram", {})
    agent_config = settings.get("agent", {})
    store_config = settings.get("store", {})
    
    # 3. Initialize LLMClient from config
    llm_client = LLMClient(
        base_url=llm_config.get("base_url", "https://api.openai.com/v1"),
        api_key=llm_config.get("api_key", ""),
        model=llm_config.get("model", "gpt-4"),
    )
    logger.info(f"Initialized LLM client: model={llm_client.model}")
    
    # 4. Initialize SkillRegistry, call auto_discover(), then load_yaml_skills()
    skills = SkillRegistry()
    
    # Auto-discover skills from the skills package
    discovered_count = skills.auto_discover("skills")
    logger.info(f"Auto-discovered {discovered_count} skills")
    
    # Load YAML-based skills from config/skills.yaml
    yaml_skills_path = PROJECT_ROOT / "config" / "skills.yaml"
    yaml_count = load_yaml_skills(skills, str(yaml_skills_path))
    logger.info(f"Loaded {yaml_count} YAML skills")
    
    # Log startup info: number of skills loaded, skill names
    total_skills = len(skills)
    skill_names = list(skills._skills.keys())
    logger.info(f"Total skills loaded: {total_skills}")
    logger.info(f"Skill names: {', '.join(skill_names)}")
    
    # 5. Initialize ContextManager (requires store, so we initialize store first)
    store_path = store_config.get("sqlite_path", "./data/kali_agent.db")
    store = SQLiteStore(db_path=store_path)
    
    # 7. Initialize store, call await store.connect()
    await store.connect()
    logger.info(f"Initialized SQLite store at {store_path}")

    # Initialize AgentLoop with llm, skills, store
    agent_loop = AgentLoop(
        llm=llm_client,
        skills=skills,
        store=store,
    )
    logger.info("Initialized agent loop")
    
    # Extract Telegram configuration
    token = telegram_config.get("token", "")
    allowed_users = telegram_config.get("allowed_users", [])
    
    # Filter out empty entries from allowed_users (handles YAML with empty list items)
    allowed_users = [uid for uid in allowed_users if uid and not isinstance(uid, list)]
    
    # 8. Initialize TelegramInterface with token, allowed_users, agent_loop, skills
    bot = TelegramInterface(
        token=token,
        allowed_users=allowed_users,
        agent_loop=agent_loop,
        skills=skills,
    )
    logger.info("Initialized Telegram bot interface")
    
    # 9. Wire callbacks: agent.status_callback = bot.send_status, 
    #    agent.confirm_callback = bot.request_confirmation
    agent_loop.status_callback = bot.send_status
    agent_loop.confirm_callback = bot.request_confirmation
    logger.info("Wired agent callbacks to bot")
    
    # Create shutdown event for coordinated shutdown
    shutdown_event = asyncio.Event()
    
    # 10. Register SIGTERM and SIGINT handlers that stop all active tasks and close bot session
    def signal_handler(signum: int, frame: Any) -> None:
        """Handle shutdown signals by stopping all active tasks."""
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name} signal, initiating graceful shutdown...")
        shutdown_event.set()
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Registered SIGTERM and SIGINT signal handlers")
    
    # 11. Log startup info (already logged above with skill details)
    logger.info("=" * 50)
    logger.info("Kali Agent daemon starting...")
    logger.info(f"Skills loaded: {total_skills}")
    logger.info(f"Allowed users: {len(allowed_users)}")
    logger.info("=" * 50)
    
    # 12. Call await bot.start() with graceful shutdown handling
    try:
        # Start bot in background task
        bot_task = asyncio.create_task(bot.start())
        logger.debug("Created bot task, waiting for shutdown signal or bot completion")
        
        # Wait for either bot to stop or shutdown signal
        # Use wait() with FIRST_COMPLETED to avoid hanging on bot_task
        done, pending = await asyncio.wait(
            [bot_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        
        logger.info(f"Wait completed. Done tasks: {len(done)}, Pending tasks: {len(pending)}")
        
        # Cancel any pending tasks
        for task in pending:
            logger.info(f"Cancelling pending task: {task}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"Task cancelled successfully")
        
        # Stop the bot dispatcher explicitly
        if not bot_task.done():
            logger.info("Explicitly stopping bot dispatcher...")
            await bot.stop()
            logger.info("Bot dispatcher stopped")
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)
    finally:
        # Graceful shutdown: stop all active tasks and close bot session
        logger.info("Initiating graceful shutdown...")
        
        # Stop all active agent tasks
        active_task_count = len(agent_loop.active_tasks)
        if active_task_count > 0:
            logger.info(f"Stopping {active_task_count} active tasks...")
            for task_id, task in list(agent_loop.active_tasks.items()):
                agent_loop.stop_task(task_id)
                logger.info(f"Stopped task: {task_id}")
        
        # Close the store connection
        await store.close()
        logger.info("Closed store connection")
        
        logger.info("Kali Agent daemon stopped")


if __name__ == "__main__":
    asyncio.run(main())
