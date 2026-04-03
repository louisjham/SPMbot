"""
Agent Loop - Core agent execution loop for Kali Agent.

This module implements the main agent loop that processes user messages,
interacts with the LLM, and executes skills.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

from .conditions import LoopCondition, MaxIterationsCondition
from .context import ContextManager
from .llm import LLMClient

logger = logging.getLogger(__name__)


class LoopState(Enum):
    """State of the agent loop."""
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass
class LoopResult:
    """Result of an agent loop iteration."""
    success: bool
    response: str
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class AgentLoop:
    """
    Main agent loop that orchestrates LLM interactions and skill execution.
    
    The loop processes user messages, generates LLM responses, executes
    requested skills, and manages the conversation context.
    """
    
    def __init__(
        self,
        llm_config: Any,
        agent_config: Any,
        store: Any,
    ) -> None:
        """
        Initialize the agent loop.
        
        Args:
            llm_config: LLM configuration settings.
            agent_config: Agent configuration settings.
            store: Data store for persistence.
        """
        self.llm_client = LLMClient(
            base_url=llm_config.base_url,
            api_key=llm_config.api_key,
            model=llm_config.model,
        )
        self.max_iterations = agent_config.max_iterations
        self.default_timeout = agent_config.default_timeout
        self.confirm_dangerous = agent_config.confirm_dangerous
        self.store = store
        self.context_manager = ContextManager(store)
        self.state = LoopState.IDLE
        self._pending_confirmation: Optional[dict[str, Any]] = None
    
    async def process_message(
        self,
        user_id: int,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> LoopResult:
        """
        Process a user message through the agent loop.
        
        Args:
            user_id: Telegram user ID.
            message: User message text.
            conversation_id: Optional conversation ID for context.
        
        Returns:
            LoopResult: Result of processing the message.
        """
        self.state = LoopState.PROCESSING
        actions_taken: list[dict[str, Any]] = []
        
        try:
            # Load or create conversation context
            context = await self.context_manager.get_or_create(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            
            # Add user message to context
            context.add_message(role="user", content=message)
            
            iterations = 0
            response = ""
            
            while iterations < self.max_iterations:
                iterations += 1
                logger.debug(f"Loop iteration {iterations}/{self.max_iterations}")
                
                # Generate LLM response
                llm_response = await self.llm_client.generate(
                    messages=context.get_messages(),
                    timeout=self.default_timeout,
                )
                
                response = llm_response.content
                context.add_message(role="assistant", content=response)
                
                # Check for skill execution requests
                if llm_response.tool_calls:
                    for tool_call in llm_response.tool_calls:
                        action_result = await self._execute_tool(tool_call, context)
                        actions_taken.append(action_result)
                        context.add_message(
                            role="tool",
                            content=str(action_result),
                            tool_call_id=tool_call.get("id"),
                        )
                else:
                    # No tool calls, we're done
                    break
            
            # Save updated context
            await self.context_manager.save(context)
            
            self.state = LoopState.COMPLETED
            return LoopResult(
                success=True,
                response=response,
                actions_taken=actions_taken,
            )
            
        except asyncio.TimeoutError:
            self.state = LoopState.ERROR
            logger.error("Agent loop timed out")
            return LoopResult(
                success=False,
                response="Operation timed out. Please try again.",
                error="timeout",
            )
        except Exception as e:
            self.state = LoopState.ERROR
            logger.exception("Error in agent loop")
            return LoopResult(
                success=False,
                response=f"An error occurred: {str(e)}",
                error=str(e),
            )
    
    async def _execute_tool(
        self,
        tool_call: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        """
        Execute a tool call requested by the LLM.
        
        Args:
            tool_call: Tool call specification from the LLM.
            context: Current conversation context.
        
        Returns:
            dict: Result of the tool execution.
        """
        tool_name = tool_call.get("name", "unknown")
        tool_args = tool_call.get("arguments", {})
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
        # TODO: Implement actual tool execution via skill registry
        return {
            "tool": tool_name,
            "status": "not_implemented",
            "message": f"Tool '{tool_name}' execution not yet implemented",
        }
    
    async def confirm_action(self, confirmed: bool) -> Optional[LoopResult]:
        """
        Confirm or reject a pending dangerous action.
        
        Args:
            confirmed: Whether the user confirmed the action.
        
        Returns:
            Optional[LoopResult]: Result if there was a pending action, None otherwise.
        """
        if not self._pending_confirmation:
            return None
        
        if confirmed:
            # Resume execution with confirmation
            pending = self._pending_confirmation
            self._pending_confirmation = None
            # TODO: Resume the pending action
            return LoopResult(
                success=True,
                response="Action confirmed. Proceeding...",
            )
        else:
            self._pending_confirmation = None
            self.state = LoopState.IDLE
            return LoopResult(
                success=False,
                response="Action cancelled by user.",
                error="cancelled",
            )
