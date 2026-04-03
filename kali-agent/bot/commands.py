"""
Bot Commands - Command handlers for Kali Agent Telegram bot.

This module implements all command handlers for the bot including
/start, /help, /status, /cancel, /history, and /clear.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent.loop import AgentLoop, LoopState
from agent.context import ContextManager
from .formatters import (
    format_code_block,
    format_error,
    format_history_entry,
    escape_html,
)

logger = logging.getLogger(__name__)


class BotState(StatesGroup):
    """FSM states for bot conversations."""
    idle = State()
    processing = State()
    waiting_confirmation = State()
    cancelled = State()


class CommandHandler:
    """
    Handler for all bot commands.
    
    Provides command processing for user interactions including
    conversation management and agent control.
    """
    
    def __init__(
        self,
        agent_loop: AgentLoop,
        context_manager: ContextManager,
    ) -> None:
        """
        Initialize the command handler.
        
        Args:
            agent_loop: The agent loop for processing requests.
            context_manager: Manager for conversation contexts.
        """
        self.agent_loop = agent_loop
        self.context_manager = context_manager
        self._user_states: dict[int, BotState] = {}
    
    def _get_user_state(self, user_id: int) -> BotState:
        """
        Get the current state for a user.
        
        Args:
            user_id: The Telegram user ID.
        
        Returns:
            The current bot state for the user.
        """
        return self._user_states.get(user_id, BotState.idle)
    
    def _set_user_state(self, user_id: int, state: BotState) -> None:
        """
        Set the state for a user.
        
        Args:
            user_id: The Telegram user ID.
            state: The new state to set.
        """
        self._user_states[user_id] = state
    
    async def handle_start(self, message: Message, state: FSMContext) -> None:
        """
        Handle the /start command.
        
        Initializes the conversation and welcomes the user.
        
        Args:
            message: The incoming message.
            state: The FSM context for the user.
        """
        user = message.from_user
        if not user:
            return
        
        user_id = user.id
        username = user.username or user.first_name or "User"
        
        # Clear any existing state
        await state.clear()
        self._set_user_state(user_id, BotState.idle)
        
        # Create new conversation context
        context = await self.context_manager.get_or_create(
            user_id=user_id,
            conversation_id=str(message.chat.id),
        )
        
        welcome_text = (
            f"👋 Welcome to <b>Kali Agent</b>, {escape_html(username)}!\n\n"
            "I'm an AI-powered security assistant. I can help you with:\n"
            "• Penetration testing tasks\n"
            "• Security assessments\n"
            "• Network reconnaissance\n"
            "• Vulnerability analysis\n\n"
            "Use /help to see available commands."
        )
        
        await message.answer(welcome_text, parse_mode=ParseMode.HTML)
        logger.info(f"User {user_id} ({username}) started a conversation")
    
    async def handle_help(self, message: Message) -> None:
        """
        Handle the /help command.
        
        Displays available commands and usage information.
        
        Args:
            message: The incoming message.
        """
        help_text = (
            "<b>📚 Kali Agent Commands</b>\n\n"
            "<b>Basic Commands:</b>\n"
            "/start - Initialize conversation\n"
            "/help - Show this help message\n"
            "/status - Show current agent status\n\n"
            "<b>Conversation Management:</b>\n"
            "/history - Show conversation history\n"
            "/clear - Clear conversation context\n"
            "/cancel - Cancel current operation\n\n"
            "<b>Usage Tips:</b>\n"
            "• Just send a message to interact with the agent\n"
            "• Use /cancel to stop long-running operations\n"
            "• Dangerous operations require confirmation\n"
        )
        
        await message.answer(help_text, parse_mode=ParseMode.HTML)
    
    async def handle_status(self, message: Message) -> None:
        """
        Handle the /status command.
        
        Shows the current agent and task status.
        
        Args:
            message: The incoming message.
        """
        user_id = message.from_user.id if message.from_user else 0
        user_state = self._get_user_state(user_id)
        
        # Get loop state
        loop_state = self.agent_loop.state if hasattr(self.agent_loop, 'state') else LoopState.IDLE
        
        # Get context info
        context = await self.context_manager.get(user_id, str(message.chat.id))
        message_count = len(context.messages) if context else 0
        
        status_emoji = {
            BotState.idle: "⚪️",
            BotState.processing: "🔵",
            BotState.waiting_confirmation: "🟡",
            BotState.cancelled: "🔴",
        }.get(user_state, "⚪️")
        
        loop_emoji = {
            LoopState.IDLE: "⚪️",
            LoopState.PROCESSING: "🔵",
            LoopState.WAITING_FOR_CONFIRMATION: "🟡",
            LoopState.ERROR: "🔴",
            LoopState.COMPLETED: "🟢",
        }.get(loop_state, "⚪️")
        
        status_text = (
            f"<b>📊 Agent Status</b>\n\n"
            f"<b>User State:</b> {status_emoji} {user_state.name}\n"
            f"<b>Agent State:</b> {loop_emoji} {loop_state.value}\n"
            f"<b>Messages in Context:</b> {message_count}\n"
            f"<b>User ID:</b> <code>{user_id}</code>\n"
        )
        
        await message.answer(status_text, parse_mode=ParseMode.HTML)
    
    async def handle_cancel(self, message: Message, state: FSMContext) -> None:
        """
        Handle the /cancel command.
        
        Cancels the current operation and resets state.
        
        Args:
            message: The incoming message.
            state: The FSM context for the user.
        """
        user_id = message.from_user.id if message.from_user else 0
        current_state = self._get_user_state(user_id)
        
        if current_state == BotState.idle:
            await message.answer("No active operation to cancel.")
            return
        
        # Clear state
        await state.clear()
        self._set_user_state(user_id, BotState.cancelled)
        
        # Cancel any running task in agent loop
        if hasattr(self.agent_loop, 'cancel'):
            await self.agent_loop.cancel()
        
        await message.answer(
            "✅ Operation cancelled. Send a new message to continue.",
            parse_mode=ParseMode.HTML,
        )
        
        # Reset to idle after a short delay
        self._set_user_state(user_id, BotState.idle)
        logger.info(f"User {user_id} cancelled current operation")
    
    async def handle_history(self, message: Message) -> None:
        """
        Handle the /history command.
        
        Shows the conversation history for the current session.
        
        Args:
            message: The incoming message.
        """
        user_id = message.from_user.id if message.from_user else 0
        
        context = await self.context_manager.get(user_id, str(message.chat.id))
        
        if not context or not context.messages:
            await message.answer("No conversation history found.")
            return
        
        # Build history text
        history_lines = ["<b>📜 Conversation History</b>\n"]
        
        # Limit to last 10 messages for display
        recent_messages = context.messages[-10:]
        
        for i, msg in enumerate(recent_messages, 1):
            role_emoji = "👤" if msg.role == "user" else "🤖"
            role_name = "You" if msg.role == "user" else "Agent"
            
            entry = format_history_entry(
                index=i,
                role=role_name,
                emoji=role_emoji,
                content=msg.content[:100] + ("..." if len(msg.content) > 100 else ""),
                timestamp=msg.timestamp,
            )
            history_lines.append(entry)
        
        history_text = "\n".join(history_lines)
        
        if len(context.messages) > 10:
            history_text += f"\n\n<i>Showing last 10 of {len(context.messages)} messages</i>"
        
        await message.answer(history_text, parse_mode=ParseMode.HTML)
    
    async def handle_clear(self, message: Message, state: FSMContext) -> None:
        """
        Handle the /clear command.
        
        Clears the conversation context and resets the session.
        
        Args:
            message: The incoming message.
            state: The FSM context for the user.
        """
        user_id = message.from_user.id if message.from_user else 0
        
        # Clear FSM state
        await state.clear()
        
        # Clear conversation context
        await self.context_manager.clear(user_id, str(message.chat.id))
        
        # Reset user state
        self._set_user_state(user_id, BotState.idle)
        
        await message.answer(
            "🧹 Conversation cleared. Starting fresh!",
            parse_mode=ParseMode.HTML,
        )
        
        logger.info(f"User {user_id} cleared conversation context")
    
    async def handle_confirm(self, message: Message) -> None:
        """
        Handle confirmation responses (yes/no) for dangerous operations.
        
        Args:
            message: The incoming message.
        """
        user_id = message.from_user.id if message.from_user else 0
        current_state = self._get_user_state(user_id)
        
        if current_state != BotState.waiting_confirmation:
            return
        
        text = message.text.lower().strip() if message.text else ""
        
        if text in ("yes", "y", "confirm", "proceed"):
            # Confirm the pending operation
            if hasattr(self.agent_loop, 'confirm'):
                await self.agent_loop.confirm(user_id)
            self._set_user_state(user_id, BotState.processing)
            await message.answer("✅ Confirmed. Proceeding with operation...")
        elif text in ("no", "n", "cancel", "abort"):
            # Cancel the pending operation
            if hasattr(self.agent_loop, 'reject'):
                await self.agent_loop.reject(user_id)
            self._set_user_state(user_id, BotState.idle)
            await message.answer("❌ Operation cancelled.")
        else:
            await message.answer(
                "Please respond with <b>yes</b> to confirm or <b>no</b> to cancel.",
                parse_mode=ParseMode.HTML,
            )


def setup_commands(router: Router, handler: CommandHandler) -> None:
    """
    Setup command handlers on a router.
    
    Args:
        router: The aiogram Router to register handlers on.
        handler: The CommandHandler instance with handler methods.
    """
    router.message(Command("start"))(handler.handle_start)
    router.message(Command("help"))(handler.handle_help)
    router.message(Command("status"))(handler.handle_status)
    router.message(Command("cancel"))(handler.handle_cancel)
    router.message(Command("history"))(handler.handle_history)
    router.message(Command("clear"))(handler.handle_clear)
