"""
LLM Client - OpenAI-compatible API client for Kali Agent.

This module provides a client for interacting with OpenAI-compatible APIs,
supporting both chat completions and function calling.
"""

import logging
from typing import Any

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Async client for OpenAI-compatible LLM APIs.
    
    Supports chat completions with function calling capabilities.
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        """
        Initialize the LLM client.
        
        Args:
            base_url: Base URL for the API (e.g., "https://api.openai.com/v1").
            api_key: API key for authentication.
            model: Model identifier to use for completions.
        """
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model = model
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> ChatCompletionMessage:
        """
        Generate a chat completion from the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            tools: Optional list of OpenAI-compatible tool definitions.
            temperature: Sampling temperature (0.0 to 2.0), defaults to 0.1.
        
        Returns:
            ChatCompletionMessage: The first choice's message from the response.
        
        Raises:
            APIError: If the API returns an error, wrapped with a meaningful message.
        """
        logger.debug(f"Generating chat completion with {len(messages)} messages")
        
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            response = await self.client.chat.completions.create(**kwargs)
            return response.choices[0].message
        except APIError as e:
            error_message = f"LLM request failed: {e}"
            logger.error(error_message)
            raise
    
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """
        Generate a streaming chat completion from the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            tools: Optional list of OpenAI-compatible tool definitions.
        
        Returns:
            AsyncStream: The streaming response object.
        
        Raises:
            APIError: If the API returns an error, wrapped with a meaningful message.
        """
        logger.debug(f"Starting streaming chat completion with {len(messages)} messages")
        
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            stream = await self.client.chat.completions.create(**kwargs)
            return stream
        except APIError as e:
            error_message = f"LLM streaming request failed: {e}"
            logger.error(error_message)
            raise
