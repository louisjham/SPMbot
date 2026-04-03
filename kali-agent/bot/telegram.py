"""
Telegram Bot Interface - Telegram bot integration for Kali Agent.

This module provides the TelegramInterface class for handling Telegram
bot interactions, commands, and message routing.
"""

import asyncio
import html
import logging
import uuid
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand

from ..agent.loop import AgentLoop
from ..skills.registry import SkillRegistry
from ..tasks.models import AgentTask, TaskConfig

if TYPE_CHECKING:
    pass


class TelegramInterface:
    """
    Telegram bot interface for interacting with the Kali Agent.
    
    Handles message routing, command processing, and user authorization
    for the Telegram bot platform.
    
    Attributes:
        bot: Aiogram Bot instance.
        dp: Aiogram Dispatcher instance.
        allowed_users: List of authorized Telegram user IDs.
        agent_loop: AgentLoop instance for task execution.
        skills: SkillRegistry instance for skill management.
        pending_confirms: Dictionary of pending confirmation futures.
        task_chat_map: Dictionary mapping task IDs to chat IDs.
    """

    def __init__(
        self,
        token: str,
        allowed_users: list[int],
        agent_loop: AgentLoop,
        skills: SkillRegistry,
    ) -> None:
        """
        Initialize the Telegram bot interface.
        
        Args:
            token: Telegram bot token from BotFather.
            allowed_users: List of Telegram user IDs authorized to use the bot.
            agent_loop: AgentLoop instance for executing agent tasks.
            skills: SkillRegistry instance for skill discovery and execution.
        """
        self.bot = Bot(token=token, parse_mode=ParseMode.HTML)
        self.dp = Dispatcher()
        self.allowed_users = allowed_users
        self.agent_loop = agent_loop
        self.skills = skills
        self.pending_confirms: dict[str, asyncio.Future] = {}
        self.task_chat_map: dict[str, int] = {}
        self._register_handlers()

    def _auth(self, user_id: int) -> bool:
        """
        Check if a user is authorized to use the bot.
        
        Args:
            user_id: Telegram user ID to check.
            
        Returns:
            True if the user is in the allowed_users list, False otherwise.
        """
        return user_id in self.allowed_users

    def _register_handlers(self) -> None:
        """
        Register all bot command and message handlers.
        
        This method sets up the aiogram dispatcher with handlers for
        commands, messages, and callbacks.
        """
        @self.dp.message(CommandStart())
        async def handle_start(message: types.Message) -> None:
            """Handle /start command with welcome message."""
            if not self._auth(message.from_user.id):
                return
            welcome_text = (
                "<b>Welcome to Kali Agent!</b>\n\n"
                "Available commands:\n"
                "/start - Show this welcome message\n"
                "/skills - List available skills and commands\n"
                "/status - Show active tasks"
            )
            await message.reply(welcome_text, parse_mode=ParseMode.HTML)

        @self.dp.message(Command("skills"))
        async def handle_skills(message: types.Message) -> None:
            """Handle /skills command to list available skills."""
            if not self._auth(message.from_user.id):
                return
            commands = self.skills.all_slash_commands()
            if not commands:
                await message.reply("No skills available.", parse_mode=ParseMode.HTML)
                return
            skills_list = "\n".join(f"• <code>{html.escape(cmd)}</code>" for cmd in commands)
            await message.reply(
                f"<b>Available Skills:</b>\n{skills_list}",
                parse_mode=ParseMode.HTML,
            )

        @self.dp.message(Command("status"))
        async def handle_status(message: types.Message) -> None:
            """Handle /status command to show active tasks."""
            if not self._auth(message.from_user.id):
                return
            if not self.agent_loop.active_tasks:
                await message.reply("No active tasks", parse_mode=ParseMode.HTML)
                return
            status_lines = []
            for task_id, task in self.agent_loop.active_tasks.items():
                goal_truncated = html.escape(task.config.goal[:80])
                status_lines.append(
                    f"<b>Task:</b> <code>{html.escape(task_id)}</code>\n"
                    f"<b>State:</b> {html.escape(task.state.value)}\n"
                    f"<b>Iteration:</b> {task.current_iteration}\n"
                    f"<b>Goal:</b> {goal_truncated}"
                )
            await message.reply(
                "\n\n".join(status_lines),
                parse_mode=ParseMode.HTML,
            )

        @self.dp.message(Command("task"))
        async def handle_task(message: types.Message) -> None:
            """Handle /task command to start a new agent task."""
            if not self._auth(message.from_user.id):
                return
            
            # Extract goal text from message
            goal_text = message.text[len("/task "):].strip() if message.text else ""
            if not goal_text:
                await message.reply(
                    "Usage: /task <goal>\nExample: /task Scan example.com for vulnerabilities",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            # Generate task ID and store chat mapping
            task_id = str(uuid.uuid4())[:8]
            self.task_chat_map[task_id] = message.chat.id
            
            # Create and launch the task
            task = AgentTask(task_id=task_id, config=TaskConfig(goal=goal_text))
            await message.reply(
                f"🚀 Task {task_id} started",
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(self.agent_loop.run(task))

        @self.dp.message(Command("stop"))
        async def handle_stop(message: types.Message) -> None:
            """Handle /stop command to stop an active task."""
            if not self._auth(message.from_user.id):
                return
            
            # Parse optional task_id from message
            task_id = message.text[len("/stop "):].strip() if message.text else ""
            
            # If no task_id provided, use the last active task
            if not task_id:
                if not self.agent_loop.active_tasks:
                    await message.reply("No active tasks", parse_mode=ParseMode.HTML)
                    return
                # Get the last key from active_tasks
                task_id = list(self.agent_loop.active_tasks.keys())[-1]
            
            # Stop the task
            self.agent_loop.stop_task(task_id)
            await message.reply(
                f"⏹️ Task {html.escape(task_id)} stopped",
                parse_mode=ParseMode.HTML,
            )

        @self.dp.message(Command("confirm"))
        async def handle_confirm(message: types.Message) -> None:
            """Handle /confirm command to approve a pending action."""
            if not self._auth(message.from_user.id):
                return
            self._resolve_confirm(True)
            await message.reply("✅ Confirmed", parse_mode=ParseMode.HTML)

        @self.dp.message(Command("deny"))
        async def handle_deny(message: types.Message) -> None:
            """Handle /deny command to reject a pending action."""
            if not self._auth(message.from_user.id):
                return
            self._resolve_confirm(False)
            await message.reply("❌ Denied", parse_mode=ParseMode.HTML)

        # Register dynamic skill commands
        self._register_skill_commands()

    def _register_skill_commands(self) -> None:
        """
        Register handlers for all skill slash commands.
        
        Iterates through the skill registry's slash command map and creates
        a dedicated handler for each skill command. Uses a separate method
        to avoid closure variable capture bugs.
        """
        for cmd_str, skill_name in self.skills._slash_map.items():
            cmd_clean = cmd_str.lstrip("/")
            skill = self.skills.get(skill_name)
            if not skill:
                continue

            self._make_skill_handler(cmd_clean, skill)

    def _make_skill_handler(self, cmd_clean: str, skill) -> None:
        """
        Create and register a command handler for a skill.
        
        This method exists separately to avoid closure variable capture bugs.
        When the handler is called later, 'skill' is bound as a parameter,
        not captured from a loop variable.
        
        Args:
            cmd_clean: The command name without leading slash.
            skill: The skill instance to execute.
        """
        @self.dp.message(Command(cmd_clean))
        async def handler(message: types.Message) -> None:
            """Handle a skill slash command."""
            if not self._auth(message.from_user.id):
                return
            parts = message.text.split(maxsplit=1) if message.text else []
            args_text = parts[1] if len(parts) > 1 else ""
            task_id = str(uuid.uuid4())[:8]
            self.task_chat_map[task_id] = message.chat.id
            goal = (
                f"Use the {skill.name} skill with these parameters/target: {args_text}. "
                f"Analyze the results thoroughly and report findings."
            )
            task = AgentTask(
                task_id=task_id,
                config=TaskConfig(goal=goal, max_iterations=10),
            )
            await message.reply(
                f"🔧 Running <code>{html.escape(skill.name)}</code> — task <code>{html.escape(task_id)}</code>",
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(self.agent_loop.run(task))

    def _resolve_confirm(self, value: bool) -> None:
        """
        Resolve a pending confirmation future with the given value.
        
        Iterates through pending confirmation futures and sets the result
        on the first one that is not yet completed.
        
        Args:
            value: True to confirm, False to deny.
        """
        for task_id, fut in self.pending_confirms.items():
            if not fut.done():
                fut.set_result(value)
                break

    async def request_confirmation(
        self, task_id: str, skill_name: str, args: dict
    ) -> bool:
        """
        Request user confirmation for a skill execution.
        
        Creates a future that waits for user confirmation via /confirm or /deny
        commands. Times out after 120 seconds if no response is received.
        
        Args:
            task_id: The ID of the task requesting confirmation.
            skill_name: The name of the skill to be executed.
            args: The arguments that will be passed to the skill.
            
        Returns:
            True if the user confirmed, False if denied or timed out.
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self.pending_confirms[task_id] = fut
        
        try:
            result = await asyncio.wait_for(fut, timeout=120.0)
            return result
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending_confirms.pop(task_id, None)

    async def send_status(self, task_id: str, text: str) -> None:
        """
        Send a status update message to the chat associated with a task.
        
        Splits long messages into chunks at newline boundaries (max 4000 chars each)
        and sends them as HTML-formatted messages. Escapes bare HTML entities
        in text that doesn't contain intentional HTML tags.
        
        Args:
            task_id: The ID of the task to send status for.
            text: The status text to send.
        """
        chat_id = self.task_chat_map.get(task_id)
        if not chat_id:
            return
        
        # Split text into chunks at newline boundaries, max 4000 chars each
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= 4000:
                chunks.append(remaining)
                break
            
            # Find a newline boundary within the last 500 chars before 4000
            split_point = 4000
            newline_search_start = max(3500, 0)
            newline_pos = remaining.rfind('\n', newline_search_start, 4000)
            if newline_pos > newline_search_start:
                split_point = newline_pos + 1  # Include the newline in this chunk
            
            chunks.append(remaining[:split_point])
            remaining = remaining[split_point:]
        
        # Send each chunk
        for chunk in chunks:
            # Escape bare HTML if the chunk doesn't contain intentional tags
            if '<b>' not in chunk and '<pre>' not in chunk:
                chunk = html.escape(chunk)
            
            try:
                await self.bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.error(f"Failed to send status message: {e}")

    async def setup_bot_commands(self) -> None:
        """
        Set up bot commands for the Telegram menu.
        
        Registers core commands (task, skills, stop, status, confirm, deny)
        and all skill slash commands from the skill registry.
        """
        commands = [
            BotCommand(command="task", description="Start a new agent task"),
            BotCommand(command="skills", description="List available skills"),
            BotCommand(command="stop", description="Stop an active task"),
            BotCommand(command="status", description="Show active tasks"),
            BotCommand(command="confirm", description="Confirm a pending action"),
            BotCommand(command="deny", description="Deny a pending action"),
        ]
        
        # Add skill slash commands
        for cmd in self.skills.all_slash_commands():
            # Remove leading slash if present
            cmd_name = cmd.lstrip('/')
            commands.append(BotCommand(command=cmd_name, description=f"Skill: {cmd_name}"))
        
        await self.bot.set_my_commands(commands)

    async def start(self) -> None:
        """
        Start the Telegram bot polling loop.
        
        Sets up bot commands and begins long polling to receive updates
        from Telegram servers.
        """
        await self.setup_bot_commands()
        await self.dp.start_polling(self.bot)
