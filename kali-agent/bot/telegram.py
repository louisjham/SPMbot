"""
Telegram Bot - Main Telegram bot implementation for Kali Agent.

This module provides the TelegramBot and TelegramInterface classes that handle all Telegram
interactions using aiogram 3.x, including message handling, middleware,
and integration with the agent loop.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

from agent.loop import AgentLoop
from agent.context import ContextManager
from skills.registry import SkillRegistry
from tasks.models import AgentTask, TaskConfig, TaskState
from .commands import CommandHandler
from .formatters import format_error, format_response, truncate_message

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """
    Middleware for authenticating users against the allowed users list.
    
    Checks if the user ID is in the allowed_users list before allowing
    access to bot commands and message handling.
    """
    
    def __init__(self, allowed_users: list[int]) -> None:
        """
        Initialize the auth middleware.
        
        Args:
            allowed_users: List of Telegram user IDs allowed to use the bot.
        """
        self.allowed_users = set(allowed_users)
    
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Any],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """
        Process incoming messages and check authorization.
        
        Args:
            handler: The next handler in the middleware chain.
            event: The incoming message event.
            data: Additional data passed through the middleware.
        
        Returns:
            The handler result if authorized, None otherwise.
        """
        user_id = event.from_user.id if event.from_user else None
        
        if user_id is None:
            logger.warning("Received message without user ID")
            return None
        
        if not self.allowed_users or user_id in self.allowed_users:
            return await handler(event, data)
        
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        await event.answer(
            "⛔ Unauthorized. Your user ID is not in the allowed list.",
            parse_mode=ParseMode.HTML,
        )
        return None


class TelegramBot:
    """
    Main Telegram bot class for Kali Agent.
    
    Handles all Telegram interactions including message processing,
    command handling, and integration with the agent loop.
    
    Example:
        async with TelegramBot(config) as bot:
            await bot.run()
    """
    
    def __init__(
        self,
        token: str,
        allowed_users: list[int],
        agent_loop: AgentLoop,
        context_manager: ContextManager,
    ) -> None:
        """
        Initialize the Telegram bot.
        
        Args:
            token: Telegram bot token from @BotFather.
            allowed_users: List of user IDs allowed to interact with the bot.
            agent_loop: The agent loop for processing messages.
            context_manager: Manager for conversation contexts.
        """
        self.token = token
        self.allowed_users = allowed_users
        self.agent_loop = agent_loop
        self.context_manager = context_manager
        
        # Initialize bot and dispatcher
        self.bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self.router = Router()
        
        # Initialize command handler
        self.command_handler = CommandHandler(
            agent_loop=agent_loop,
            context_manager=context_manager,
        )
        
        # Setup middleware and handlers
        self._setup_middleware()
        self._setup_handlers()
    
    def _setup_middleware(self) -> None:
        """Configure middleware for the bot."""
        auth_middleware = AuthMiddleware(self.allowed_users)
        self.router.message.middleware(auth_middleware)
    
    def _setup_handlers(self) -> None:
        """Configure message and command handlers."""
        # Command handlers
        self.router.message(Command("start"))(self.command_handler.handle_start)
        self.router.message(Command("help"))(self.command_handler.handle_help)
        self.router.message(Command("status"))(self.command_handler.handle_status)
        self.router.message(Command("cancel"))(self.command_handler.handle_cancel)
        self.router.message(Command("history"))(self.command_handler.handle_history)
        self.router.message(Command("clear"))(self.command_handler.handle_clear)
        
        # Default message handler for non-command messages
        self.router.message()(self._handle_message)
        
        # Include router in dispatcher
        self.dp.include_router(self.router)
    
    async def _handle_message(self, message: Message) -> None:
        """
        Handle regular (non-command) messages.
        
        Processes the message through the agent loop and sends
        the response back to the user.
        
        Args:
            message: The incoming Telegram message.
        """
        if not message.text or not message.from_user:
            return
        
        user_id = message.from_user.id
        user_input = message.text.strip()
        
        logger.info(f"Processing message from user {user_id}: {user_input[:50]}...")
        
        # Send typing indicator
        await message.bot.send_chat_action(
            chat_id=message.chat.id,
            action="typing",
        )
        
        try:
            # Get or create conversation context
            context = await self.context_manager.get_or_create(
                user_id=user_id,
                conversation_id=str(message.chat.id),
            )
            
            # Process through agent loop
            result = await self.agent_loop.process(
                context=context,
                user_input=user_input,
            )
            
            # Format and send response
            response = format_response(result.response)
            
            # Handle message length limits
            if len(response) > 4096:
                chunks = truncate_message(response, max_length=4000)
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
            
        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            error_msg = format_error(str(e))
            await message.answer(error_msg)
    
    async def start(self) -> None:
        """
        Start the bot polling for updates.
        
        This method starts long polling for updates from Telegram.
        """
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot, allowed_updates=Update.ALL_TYPES)
    
    async def stop(self) -> None:
        """
        Stop the bot and cleanup resources.
        
        Cancels polling and closes the bot session.
        """
        logger.info("Stopping Telegram bot...")
        await self.dp.stop_polling()
        await self.bot.session.close()
    
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = ParseMode.HTML,
    ) -> Message:
        """
        Send a message to a specific chat.
        
        Args:
            chat_id: Target chat ID.
            text: Message text to send.
            parse_mode: Parse mode for the message (HTML, MarkdownV2, or None).
        
        Returns:
            The sent message object.
        
        Raises:
            TelegramAPIError: If the message fails to send.
        """
        return await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
        )
    
    async def broadcast(
        self,
        user_ids: list[int],
        text: str,
    ) -> dict[int, bool]:
        """
        Broadcast a message to multiple users.
        
        Args:
            user_ids: List of user IDs to send the message to.
            text: Message text to broadcast.
        
        Returns:
            Dictionary mapping user IDs to success status.
        """
        results: dict[int, bool] = {}
        
        for user_id in user_ids:
            try:
                await self.send_message(chat_id=user_id, text=text)
                results[user_id] = True
            except TelegramAPIError as e:
                logger.error(f"Failed to send message to {user_id}: {e}")
                results[user_id] = False
        
        return results


class TelegramInterface:
    """
    Telegram interface for Kali Agent with task management and skill commands.
    
    Provides a comprehensive interface for managing agent tasks through Telegram,
    including task creation, status monitoring, confirmation handling, and
    skill-specific slash commands.
    
    Attributes:
        bot: aiogram Bot instance with HTML parse mode.
        dp: aiogram Dispatcher for handling updates.
        agent_loop: The agent loop for executing tasks.
        skills: Registry of available skills.
        store: Optional SQLite store for task history.
        pending_confirms: Dictionary mapping task_id to confirmation Future.
        task_chat_map: Dictionary mapping task_id to chat_id.
    """
    
    def __init__(
        self,
        token: str,
        allowed_users: list[int],
        agent_loop: AgentLoop,
        skills: SkillRegistry,
        store: Any = None,
    ) -> None:
        """
        Initialize the Telegram interface.
        
        Args:
            token: Telegram bot token from @BotFather.
            allowed_users: List of Telegram user IDs allowed to use the bot.
            agent_loop: The agent loop for executing tasks.
            skills: Registry of available skills.
            store: Optional SQLite store for querying task history.
        """
        self.token = token
        self.allowed_users = set(allowed_users)
        self.agent_loop = agent_loop
        self.skills = skills
        self.store = store
        
        # Initialize bot and dispatcher with HTML parse mode to avoid markdown issues
        self.bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        
        # Internal state management
        self.pending_confirms: dict[str, asyncio.Future] = {}
        self.task_chat_map: dict[str, int] = {}
        self._user_recent_tasks: dict[int, str] = {}  # user_id -> most recent task_id
        
        # Register all command handlers
        self._register_handlers()
        self._register_skill_commands()
    
    def _auth(self, user_id: int) -> bool:
        """
        Check if a user ID is authorized to use the bot.
        
        Args:
            user_id: The Telegram user ID to check.
        
        Returns:
            True if the user is allowed, False otherwise.
        """
        return user_id in self.allowed_users
    
    def _register_handlers(self) -> None:
        """Register all command handlers with the dispatcher."""
        
        @self.dp.message(Command("start"))
        async def handle_start(message: Message) -> None:
            """Handle /start command - send welcome message with command list."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            welcome_text = (
                "<b>🤖 Kali Agent Bot</b>\n\n"
                "Welcome! I'm an AI-powered penetration testing assistant.\n\n"
                "<b>Available Commands:</b>\n"
                "/start - Show this welcome message\n"
                "/task <goal> - Create a new agent task\n"
                "/stop [task_id] - Stop a running task (defaults to most recent)\n"
                "/status - List all active tasks\n"
                "/skills - List all available skills and commands\n"
                "/confirm - Confirm a pending dangerous operation\n"
                "/deny - Deny a pending dangerous operation\n"
                "/history - Show recent completed tasks\n"
            )
            await message.answer(welcome_text)
        
        @self.dp.message(Command("task"))
        async def handle_task(message: Message, command: CommandObject) -> None:
            """Handle /task command - create a new agent task."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            # Get the goal from command args
            goal = command.args
            if not goal or not goal.strip():
                await message.answer(
                    "❌ Please provide a goal.\n"
                    "Usage: /task <goal>"
                )
                return
            
            goal = goal.strip()
            
            # Generate short task ID (first 8 chars of UUID4)
            from uuid import uuid4
            task_id = uuid4().hex[:8]
            
            # Store chat mapping for status updates
            chat_id = message.chat.id
            self.task_chat_map[task_id] = chat_id
            self._user_recent_tasks[user_id] = task_id
            
            # Create task configuration
            config = TaskConfig(goal=goal)
            
            # Create agent task
            task = AgentTask(
                task_id=task_id,
                config=config,
            )
            
            # Create asyncio task for agent execution
            asyncio.create_task(self.agent_loop.run(task))
            
            await message.answer(
                f"✅ Task created\n"
                f"<b>ID:</b> <code>{task_id}</code>\n"
                f"<b>Goal:</b> {goal}"
            )
        
        @self.dp.message(Command("stop"))
        async def handle_stop(message: Message, command: CommandObject) -> None:
            """Handle /stop command - stop a running task."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            # Get task_id from args or use most recent
            task_id = command.args.strip() if command.args else None
            
            if not task_id:
                # Default to most recent active task for this user
                task_id = self._user_recent_tasks.get(user_id)
                if not task_id:
                    await message.answer(
                        "❌ No task specified and no recent task found.\n"
                        "Usage: /stop [task_id]"
                    )
                    return
            
            # Try to stop the task
            success = self.agent_loop.stop_task(task_id)
            
            if success:
                await message.answer(f"✅ Task <code>{task_id}</code> signalled to stop.")
            else:
                await message.answer(
                    f"❌ Task <code>{task_id}</code> not found or already completed."
                )
        
        @self.dp.message(Command("status"))
        async def handle_status(message: Message) -> None:
            """Handle /status command - list all active tasks."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            active_tasks = self.agent_loop.active_tasks
            
            if not active_tasks:
                await message.answer("📋 No active tasks.")
                return
            
            lines = ["<b>📋 Active Tasks:</b>\n"]
            
            for task_id, task in active_tasks.items():
                state_emoji = {
                    TaskState.PENDING: "⏳",
                    TaskState.RUNNING: "🔄",
                    TaskState.WAITING_CONFIRMATION: "⏸️",
                    TaskState.PAUSED: "⏸️",
                    TaskState.COMPLETED: "✅",
                    TaskState.FAILED: "❌",
                    TaskState.STOPPED: "🛑",
                }.get(task.state, "❓")
                
                lines.append(
                    f"{state_emoji} <b>{task_id}</b>\n"
                    f"   State: {task.state.value}\n"
                    f"   Iteration: {task.current_iteration}/{task.config.max_iterations}\n"
                    f"   Goal: {task.config.goal[:100]}{'...' if len(task.config.goal) > 100 else ''}\n"
                )
            
            response = "\n".join(lines)
            
            # Split if too long
            if len(response) > 4000:
                chunks = self._split_message(response, 4000)
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
        
        @self.dp.message(Command("skills"))
        async def handle_skills(message: Message) -> None:
            """Handle /skills command - list all registered skills."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            skills_dict = self.skills._skills
            slash_map = self.skills._slash_map
            
            if not skills_dict:
                await message.answer("📋 No skills registered.")
                return
            
            lines = ["<b>🔧 Available Skills:</b>\n"]
            
            for skill_name, skill in skills_dict.items():
                dangerous_marker = " ⚠️" if skill.dangerous else ""
                slash_cmd = f" (/{skill.slash_command})" if skill.slash_command else ""
                lines.append(
                    f"• <b>{skill_name}</b>{slash_cmd}{dangerous_marker}\n"
                    f"  {skill.description[:80]}{'...' if len(skill.description) > 80 else ''}"
                )
            
            if slash_map:
                lines.append("\n<b>Slash Commands:</b>")
                for cmd, skill_name in slash_map.items():
                    lines.append(f"/{cmd} → {skill_name}")
            
            response = "\n".join(lines)
            
            # Split if too long
            if len(response) > 4000:
                chunks = self._split_message(response, 4000)
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(response)
        
        @self.dp.message(Command("confirm"))
        async def handle_confirm(message: Message) -> None:
            """Handle /confirm command - resolve pending confirmation with True."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            if not self.pending_confirms:
                await message.answer("❌ No pending confirmations.")
                return
            
            # Get the first pending confirmation
            task_id, future = next(iter(self.pending_confirms.items()))
            del self.pending_confirms[task_id]
            
            if not future.done():
                future.set_result(True)
                await message.answer(f"✅ Confirmation accepted for task <code>{task_id}</code>")
            else:
                await message.answer("⚠️ Confirmation already resolved.")
        
        @self.dp.message(Command("deny"))
        async def handle_deny(message: Message) -> None:
            """Handle /deny command - resolve pending confirmation with False."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            if not self.pending_confirms:
                await message.answer("❌ No pending confirmations.")
                return
            
            # Get the first pending confirmation
            task_id, future = next(iter(self.pending_confirms.items()))
            del self.pending_confirms[task_id]
            
            if not future.done():
                future.set_result(False)
                await message.answer(f"❌ Confirmation denied for task <code>{task_id}</code>")
            else:
                await message.answer("⚠️ Confirmation already resolved.")
        
        @self.dp.message(Command("history"))
        async def handle_history(message: Message) -> None:
            """Handle /history command - show recent completed tasks."""
            if not message.from_user:
                return
            
            user_id = message.from_user.id
            if not self._auth(user_id):
                await message.answer("⛔ Unauthorized access.")
                return
            
            if not self.store:
                await message.answer("❌ Task history not available (no store configured).")
                return
            
            try:
                # Query store for recent tasks
                tasks = await self.store.get_task_history(limit=10)
                
                if not tasks:
                    await message.answer("📋 No task history found.")
                    return
                
                lines = ["<b>📜 Recent Tasks:</b>\n"]
                
                for task in tasks:
                    state_emoji = {
                        "completed": "✅",
                        "failed": "❌",
                        "stopped": "🛑",
                    }.get(task.get("state", ""), "❓")
                    
                    goal = task.get("goal", "N/A")
                    if len(goal) > 60:
                        goal = goal[:60] + "..."
                    
                    created = task.get("created_at", "N/A")
                    if created and len(created) > 19:
                        created = created[:19]  # Truncate microseconds
                    
                    lines.append(
                        f"{state_emoji} <b>{task.get('id', 'N/A')}</b>\n"
                        f"   Goal: {goal}\n"
                        f"   State: {task.get('state', 'N/A')}\n"
                        f"   Created: {created}\n"
                    )
                
                response = "\n".join(lines)
                
                # Split if too long
                if len(response) > 4000:
                    chunks = self._split_message(response, 4000)
                    for chunk in chunks:
                        await message.answer(chunk)
                else:
                    await message.answer(response)
                    
            except Exception as e:
                logger.exception(f"Error fetching task history: {e}")
                await message.answer(f"❌ Error fetching history: {str(e)}")
    
    def _register_skill_commands(self) -> None:
        """
        Register handlers for skill-specific slash commands.
        
        Iterates through the skills._slash_map and creates a handler for each
        slash command that creates a task with the skill execution goal.
        """
        slash_map = self.skills._slash_map
        
        for slash_command, skill_name in slash_map.items():
            # Create handler for this slash command
            def make_handler(skill_name: str, slash_cmd: str):
                async def handler(message: Message, command: CommandObject) -> None:
                    """Handle skill-specific slash command."""
                    if not message.from_user:
                        return
                    
                    user_id = message.from_user.id
                    if not self._auth(user_id):
                        await message.answer("⛔ Unauthorized access.")
                        return
                    
                    # Get user args
                    user_args = command.args.strip() if command.args else ""
                    
                    # Generate short task ID
                    from uuid import uuid4
                    task_id = uuid4().hex[:8]
                    
                    # Store chat mapping
                    chat_id = message.chat.id
                    self.task_chat_map[task_id] = chat_id
                    self._user_recent_tasks[user_id] = task_id
                    
                    # Build goal for skill execution
                    goal = f"Use {skill_name} with target/params: {user_args}. Analyze results."
                    
                    # Create task configuration
                    config = TaskConfig(goal=goal)
                    
                    # Create agent task
                    task = AgentTask(
                        task_id=task_id,
                        config=config,
                    )
                    
                    # Create asyncio task for agent execution
                    asyncio.create_task(self.agent_loop.run(task))
                    
                    await message.answer(
                        f"✅ Skill task created\n"
                        f"<b>ID:</b> <code>{task_id}</code>\n"
                        f"<b>Skill:</b> {skill_name}\n"
                        f"<b>Params:</b> {user_args or 'none'}"
                    )
                
                return handler
            
            # Register the handler with the dispatcher
            handler = make_handler(skill_name, slash_command)
            self.dp.message(Command(slash_command))(handler)
            
            logger.debug(f"Registered slash command /{slash_command} -> {skill_name}")
    
    def _split_message(self, text: str, max_length: int = 4000) -> list[str]:
        """
        Split a long message into chunks that fit within Telegram's limits.
        
        Args:
            text: The text to split.
            max_length: Maximum length per chunk.
        
        Returns:
            List of text chunks.
        """
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        remaining = text
        
        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break
            
            # Find a good break point (newline preferred)
            break_point = remaining.rfind('\n', 0, max_length)
            if break_point == -1:
                break_point = max_length
            
            chunks.append(remaining[:break_point])
            remaining = remaining[break_point:].lstrip('\n')
        
        return chunks
    
    async def send_status(self, task_id: str, text: str) -> None:
        """
        Send a status update message for a task.
        
        Looks up the chat_id from task_chat_map and sends the message.
        Handles message splitting for texts > 4000 chars and catches
        Telegram API errors.
        
        Args:
            task_id: The task ID to send status for.
            text: The status message text to send.
        """
        chat_id = self.task_chat_map.get(task_id)
        
        if chat_id is None:
            logger.warning(f"No chat mapping found for task {task_id}")
            return
        
        try:
            # Split message if too long
            if len(text) > 4000:
                chunks = self._split_message(text, 4000)
                for chunk in chunks:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=ParseMode.HTML,
                    )
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
        except TelegramAPIError as e:
            logger.error(f"Telegram API error sending status for task {task_id}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error sending status for task {task_id}: {e}")
    
    async def start(self) -> None:
        """
        Start the bot polling for updates.
        
        This method starts long polling for updates from Telegram.
        """
        logger.info("Starting Telegram interface...")
        await self.dp.start_polling(self.bot, allowed_updates=Update.ALL_TYPES)
    
    async def stop(self) -> None:
        """
        Stop the bot and cleanup resources.
        
        Cancels polling and closes the bot session.
        """
        logger.info("Stopping Telegram interface...")
        await self.dp.stop_polling()
        await self.bot.session.close()
    
    def create_confirm_future(self, task_id: str) -> asyncio.Future:
        """
        Create a Future for pending confirmation and store it.
        
        Args:
            task_id: The task ID waiting for confirmation.
        
        Returns:
            The asyncio.Future that will be resolved by /confirm or /deny.
        """
        future = asyncio.get_event_loop().create_future()
        self.pending_confirms[task_id] = future
        return future
