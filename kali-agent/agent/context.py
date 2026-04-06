"""
Context Manager - Conversation context management for Kali Agent.

This module handles loading, saving, and managing conversation context
including message history and metadata.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single message in the conversation."""
    role: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tool_call_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary format for LLM API."""
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class ConversationContext:
    """Context for a single conversation."""
    conversation_id: str
    user_id: int
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def add_message(
        self,
        role: str,
        content: str,
        tool_call_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """
        Add a message to the conversation.
        
        Args:
            role: Message role (user, assistant, system, tool).
            content: Message content.
            tool_call_id: Optional tool call ID for tool responses.
            metadata: Optional metadata dictionary.
        
        Returns:
            Message: The created message.
        """
        message = Message(
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.updated_at = datetime.now(timezone.utc)
        return message
    
    def get_messages(self) -> list[dict[str, Any]]:
        """
        Get all messages in LLM API format.
        
        Returns:
            list: List of message dictionaries.
        """
        return [msg.to_dict() for msg in self.messages]
    
    def get_last_n_messages(self, n: int) -> list[dict[str, Any]]:
        """
        Get the last n messages in LLM API format.
        
        Args:
            n: Number of messages to retrieve.
        
        Returns:
            list: List of the most recent n message dictionaries.
        """
        return [msg.to_dict() for msg in self.messages[-n:]]
    
    def clear_messages(self) -> None:
        """Clear all messages from the conversation."""
        self.messages.clear()
        self.updated_at = datetime.now(timezone.utc)


class ContextManager:
    """
    Manages conversation contexts with persistence support.
    
    Handles creation, retrieval, and persistence of conversation contexts.
    """
    
    def __init__(self, store: Any) -> None:
        """
        Initialize the context manager.
        
        Args:
            store: Data store for persisting contexts.
        """
        self.store = store
        self._cache: dict[str, ConversationContext] = {}
    
    async def get_or_create(
        self,
        user_id: int,
        conversation_id: Optional[str] = None,
    ) -> ConversationContext:
        """
        Get an existing conversation or create a new one.
        
        Args:
            user_id: Telegram user ID.
            conversation_id: Optional existing conversation ID.
        
        Returns:
            ConversationContext: The conversation context.
        """
        if conversation_id and conversation_id in self._cache:
            return self._cache[conversation_id]
        
        if conversation_id:
            # Try to load from store
            context = await self._load_from_store(conversation_id)
            if context:
                self._cache[conversation_id] = context
                return context
        
        # Create new conversation
        new_id = conversation_id or str(uuid.uuid4())
        context = ConversationContext(
            conversation_id=new_id,
            user_id=user_id,
        )
        self._cache[new_id] = context
        return context
    
    async def _load_from_store(
        self,
        conversation_id: str,
    ) -> Optional[ConversationContext]:
        """
        Load a conversation from the data store.
        
        Args:
            conversation_id: Conversation ID to load.
        
        Returns:
            Optional[ConversationContext]: The loaded context or None.
        """
        try:
            data = await self.store.get_conversation(conversation_id)
            if data:
                return ConversationContext(
                    conversation_id=data["conversation_id"],
                    user_id=data["user_id"],
                    messages=[Message(**msg) for msg in data.get("messages", [])],
                    created_at=datetime.fromisoformat(data["created_at"]),
                    updated_at=datetime.fromisoformat(data["updated_at"]),
                    metadata=data.get("metadata", {}),
                )
        except Exception as e:
            logger.error(f"Error loading conversation {conversation_id}: {e}")
        return None
    
    async def save(self, context: ConversationContext) -> None:
        """
        Save a conversation context to the data store.
        
        Args:
            context: The conversation context to save.
        """
        data = {
            "conversation_id": context.conversation_id,
            "user_id": context.user_id,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "tool_call_id": msg.tool_call_id,
                    "metadata": msg.metadata,
                }
                for msg in context.messages
            ],
            "created_at": context.created_at.isoformat(),
            "updated_at": context.updated_at.isoformat(),
            "metadata": context.metadata,
        }
        await self.store.save_conversation(data)
        logger.debug(f"Saved conversation {context.conversation_id}")
    
    async def delete(self, conversation_id: str) -> None:
        """
        Delete a conversation context.
        
        Args:
            conversation_id: Conversation ID to delete.
        """
        if conversation_id in self._cache:
            del self._cache[conversation_id]
        await self.store.delete_conversation(conversation_id)
        logger.debug(f"Deleted conversation {conversation_id}")
