#!/usr/bin/env python3
"""
Kali Agent Daemon - Main entry point for the AI-powered security assistant.

This module initializes and runs the Kali Agent service, coordinating
between the Telegram bot interface and the underlying agent logic.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.loop import AgentLoop
from bot.telegram import TelegramBot
from store.sqlite import SQLiteStore


class LLMConfig(BaseModel):
    """LLM configuration settings."""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4"


class TelegramConfig(BaseModel):
    """Telegram bot configuration settings."""
    token: str = ""
    allowed_users: list[int] = []


class AgentConfig(BaseModel):
    """Agent configuration settings."""
    max_iterations: int = 10
    default_timeout: int = 300
    confirm_dangerous: bool = True


class StoreConfig(BaseModel):
    """Store configuration settings."""
    sqlite_path: str = "./data/kali_agent.db"


class Settings(BaseModel):
    """Application settings."""
    llm: LLMConfig = LLMConfig()
    telegram: TelegramConfig = TelegramConfig()
    agent: AgentConfig = AgentConfig()
    store: StoreConfig = StoreConfig()


def load_settings() -> Settings:
    """
    Load settings from YAML configuration file.
    
    Environment variables in the config are expanded using os.path.expandvars.
    
    Returns:
        Settings: Application settings object.
    """
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    
    if not config_path.exists():
        logging.warning(f"Config file not found at {config_path}, using defaults")
        return Settings()
    
    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)
    
    # Expand environment variables in string values
    def expand_vars(obj):
        if isinstance(obj, dict):
            return {k: expand_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_vars(item) for item in obj]
        elif isinstance(obj, str):
            return os.path.expandvars(obj)
        return obj
    
    config_data = expand_vars(config_data)
    return Settings(**config_data)


async def main() -> None:
    """
    Main entry point for the Kali Agent daemon.
    
    Initializes all components and starts the main event loop.
    """
    # Load environment variables from .env file
    load_dotenv(PROJECT_ROOT / ".env")
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(PROJECT_ROOT / "kali-agent.log"),
        ],
    )
    logger = logging.getLogger(__name__)
    
    logger.info("Starting Kali Agent daemon...")
    
    # Load settings
    settings = load_settings()
    logger.info(f"Loaded settings: agent.max_iterations={settings.agent.max_iterations}")
    
    # Initialize store
    store = SQLiteStore(settings.store.sqlite_path)
    await store.initialize()
    logger.info(f"Initialized SQLite store at {settings.store.sqlite_path}")
    
    # Initialize agent loop
    agent_loop = AgentLoop(
        llm_config=settings.llm,
        agent_config=settings.agent,
        store=store,
    )
    logger.info("Initialized agent loop")
    
    # Initialize and start Telegram bot
    bot = TelegramBot(
        token=settings.telegram.token,
        allowed_users=settings.telegram.allowed_users,
        agent_loop=agent_loop,
    )
    logger.info("Initialized Telegram bot")
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await bot.stop()
        await store.close()
        logger.info("Kali Agent daemon stopped")


if __name__ == "__main__":
    asyncio.run(main())
