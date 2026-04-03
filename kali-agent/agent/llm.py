"""
LLM Client - OpenAI-compatible API client for Kali Agent.

This module provides a client for interacting with OpenAI-compatible APIs,
supporting both chat completions and function calling.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from the LLM."""
    content: str
    tool_calls: list[dict[str, Any]]
    finish_reason: str
    usage: dict[str, int]


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
        self._tools: list[dict[str, Any]] = []
    
    def register_tool(self, tool_definition: dict[str, Any]) -> None:
        """
        Register a tool for function calling.
        
        Args:
            tool_definition: OpenAI-compatible tool definition.
        """
        self._tools.append(tool_definition)
        logger.debug(f"Registered tool: {tool_definition.get('function', {}).get('name')}")
    
    def register_tools(self, tools: list[dict[str, Any]]) -> None:
        """
        Register multiple tools for function calling.
        
        Args:
            tools: List of OpenAI-compatible tool definitions.
        """
        for tool in tools:
            self.register_tool(tool)
    
    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        timeout: int = 300,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Generate a completion from the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
        
        Returns:
            LLMResponse: The generated response.
        
        Raises:
            asyncio.TimeoutError: If the request times out.
            Exception: If the API returns an error.
        """
        logger.debug(f"Generating completion with {len(messages)} messages")
        
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        if self._tools:
            kwargs["tools"] = self._tools
            kwargs["tool_choice"] = "auto"
        
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error("LLM request timed out")
            raise
        
        choice = response.choices[0]
        
        # Extract tool calls if present
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
        
        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        )
    
    async def generate_streaming(
        self,
        messages: list[dict[str, Any]],
        *,
        timeout: int = 300,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ):
        """
        Generate a streaming completion from the LLM.
        
        Args:
            messages: List of message dictionaries.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
        
        Yields:
            str: Chunks of the generated content.
        """
        logger.debug(f"Starting streaming completion with {len(messages)} messages")
        
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        stream = await self.client.chat.completions.create(**kwargs)
        
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
