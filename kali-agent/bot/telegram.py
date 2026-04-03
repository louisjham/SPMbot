"""
Telegram Bot - Main Telegram bot implementation for Kali Agent.

This module provides the TelegramBot class that handles all Telegram
interactions using aiogram 3.x, including message handling, middleware,
and integration with the agent loop.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

from agent.loop import AgentLoop
from agent.context import ContextManager
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
    
    @asynccontextmanager
    async def lifespan(self):
        """
        Async context manager for bot lifecycle management.
        
        Yields:
            The bot instance for use within the context.
        """
        try:
            yield self
        finally:
            await self.stop()
    
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
