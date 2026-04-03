"""
Agent Loop - Core agent execution loop for Kali Agent.

This module implements the main agent loop that processes user messages,
interacts with the LLM, and executes skills.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from agent.conditions import check_stop_conditions
from agent.context import ContextManager
from agent.llm import LLMClient
from skills.registry import SkillRegistry
from tasks.models import AgentTask, TaskState

logger = logging.getLogger(__name__)

# Type aliases for callbacks
StatusCallback = Optional[Callable[[str, str], Any]]  # (task_id, message) -> awaitable
ConfirmCallback = Optional[Callable[[str, str, dict], Any]]  # (task_id, skill_name, args) -> awaitable bool


class AgentLoop:
    """
    Main agent loop that orchestrates LLM interactions and skill execution.
    
    The loop processes user messages, generates LLM responses, executes
    requested skills, and manages the conversation context.
    
    Attributes:
        llm: LLM client for generating responses.
        skills: Registry of available skills.
        context_mgr: Manager for conversation context.
        status_callback: Optional async callback for status updates.
        confirm_callback: Optional async callback for dangerous skill confirmation.
        active_tasks: Dictionary of currently active tasks by task_id.
    """
    
    def __init__(
        self,
        llm: LLMClient,
        skills: SkillRegistry,
        context_mgr: ContextManager,
        status_callback: StatusCallback = None,
        confirm_callback: ConfirmCallback = None,
    ) -> None:
        """
        Initialize the agent loop.
        
        Args:
            llm: LLM client for generating responses.
            skills: Registry of available skills.
            context_mgr: Manager for conversation context.
            status_callback: Optional async callback for status updates (task_id, message).
            confirm_callback: Optional async callback for dangerous skill confirmation
                (task_id, skill_name, args) -> bool.
        """
        self.llm = llm
        self.skills = skills
        self.context_mgr = context_mgr
        self.status_callback = status_callback
        self.confirm_callback = confirm_callback
        self.active_tasks: dict[str, AgentTask] = {}
    
    def _build_system_prompt(self, task: AgentTask) -> str:
        """
        Build the system prompt for the LLM.
        
        Constructs a system prompt including role description, current goal,
        rules, stop conditions, and iteration count.
        
        Args:
            task: The agent task to build the prompt for.
        
        Returns:
            str: The complete system prompt.
        """
        stop_conditions_text = "\n".join(
            f"  - {cond}" for cond in task.config.stop_conditions
        ) if task.config.stop_conditions else "  - None specified"
        
        system_prompt = f"""You are an advanced penetration testing AI assistant running on Kali Linux. You have access to various security tools and skills to assist with authorized security assessments.

## Current Goal
{task.config.goal}

## Rules
1. Think step-by-step before taking any action.
2. Explain your reasoning before making tool calls.
3. Analyze results carefully after each tool execution.
4. Summarize your findings periodically.
5. When you have completed the objective, say "TASK_COMPLETE" in your response.
6. If you encounter errors, try to diagnose and recover before giving up.
7. Always work within legal and ethical boundaries.

## Stop Conditions
The task will be considered complete if any of these conditions are met:
{stop_conditions_text}

## Progress
Current iteration: {task.current_iteration}/{task.config.max_iterations}

Remember to be thorough, methodical, and document your findings as you work."""
        
        return system_prompt
    
    async def run(self, task: AgentTask) -> None:
        """
        Execute the agent task loop.
        
        Main execution loop that:
        1. Sets task state to RUNNING
        2. Initializes messages with system prompt and user goal
        3. Iterates: calls LLM, executes tools, checks conditions
        4. Handles completion, cancellation, or failure
        
        Args:
            task: The agent task to execute.
        """
        task.state = TaskState.RUNNING
        self.active_tasks[task.task_id] = task
        
        try:
            await self._notify(task, f"Starting task: {task.config.goal}")
            
            # Initialize messages with system prompt and user goal
            system_prompt = self._build_system_prompt(task)
            task.messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task.config.goal},
            ]
            
            # Main execution loop
            while (
                task.state == TaskState.RUNNING
                and task.current_iteration < task.config.max_iterations
            ):
                # Check for cancellation
                if task.cancel_event.is_set():
                    task.state = TaskState.STOPPED
                    await self._notify(task, "Task cancelled by user")
                    logger.info(f"Task {task.task_id} cancelled")
                    break
                
                # Increment iteration and update system prompt
                task.current_iteration += 1
                task.messages[0]["content"] = self._build_system_prompt(task)
                
                logger.debug(
                    f"Task {task.task_id} iteration {task.current_iteration}/{task.config.max_iterations}"
                )
                
                try:
                    # Get all available tools from the skill registry
                    all_tools = self.skills.all_tools()
                    
                    # Call LLM with messages and tools
                    llm_response = await self.llm.chat(
                        messages=task.messages,
                        tools=all_tools if all_tools else None,
                    )
                    
                    # Check if response has tool calls
                    if not llm_response.tool_calls:
                        # No tool calls - append assistant message
                        assistant_content = llm_response.content or ""
                        task.messages.append({
                            "role": "assistant",
                            "content": assistant_content,
                        })
                        
                        # Check for task completion keyword
                        if "TASK_COMPLETE" in assistant_content.upper():
                            task.state = TaskState.COMPLETED
                            await self._notify(task, "Task completed successfully")
                            logger.info(f"Task {task.task_id} completed via TASK_COMPLETE")
                            continue
                    
                    else:
                        # Has tool calls - append assistant message with tool_calls
                        assistant_message: dict[str, Any] = {
                            "role": "assistant",
                            "content": llm_response.content,
                        }
                        
                        # Format tool calls for the message
                        if llm_response.tool_calls:
                            assistant_message["tool_calls"] = [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in llm_response.tool_calls
                            ]
                        
                        task.messages.append(assistant_message)
                        
                        # Process each tool call
                        for tool_call in llm_response.tool_calls:
                            tool_call_id = tool_call.id
                            function_name = tool_call.function.name
                            
                            try:
                                # Parse JSON arguments
                                arguments_str = tool_call.function.arguments
                                if isinstance(arguments_str, str):
                                    arguments = json.loads(arguments_str)
                                else:
                                    arguments = arguments_str or {}
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse tool arguments: {e}")
                                task.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": f"Error: Invalid JSON arguments - {str(e)}",
                                })
                                continue
                            
                            # Get skill from registry
                            skill = self.skills.get(function_name)
                            
                            if skill is None:
                                error_msg = f"Unknown skill: {function_name}"
                                logger.warning(error_msg)
                                task.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": error_msg,
                                })
                                continue
                            
                            # Check if skill is dangerous and requires confirmation
                            if skill.dangerous and self.confirm_callback:
                                await self._notify(
                                    task,
                                    f"Confirmation required for dangerous skill: {function_name}",
                                )
                                
                                try:
                                    confirmed = await self.confirm_callback(
                                        task.task_id,
                                        function_name,
                                        arguments,
                                    )
                                except Exception as e:
                                    logger.error(f"Error in confirm callback: {e}")
                                    confirmed = False
                                
                                if not confirmed:
                                    task.messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "content": "User denied the execution of this dangerous skill.",
                                    })
                                    await self._notify(task, f"Skill {function_name} denied by user")
                                    continue
                            
                            # Execute the skill
                            await self._notify(task, f"Running skill: {function_name}")
                            
                            try:
                                result = await skill.execute(**arguments)
                                
                                # Format result output
                                if result.success:
                                    output = result.output
                                    if result.follow_up_hint:
                                        output += f"\n\nFollow-up hint: {result.follow_up_hint}"
                                    if result.artifacts:
                                        output += f"\n\nArtifacts: {', '.join(result.artifacts)}"
                                        task.artifacts.extend(result.artifacts)
                                else:
                                    output = f"Skill failed: {result.output}"
                                
                                # Truncate output if too long (keep first 4000 chars)
                                max_output_length = 4000
                                if len(output) > max_output_length:
                                    output = output[:max_output_length] + "\n...[truncated]"
                                
                                task.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": output,
                                })
                                
                                await self._notify(
                                    task,
                                    f"Skill {function_name} completed: {'success' if result.success else 'failed'}",
                                )
                                
                            except Exception as e:
                                error_msg = f"Error executing skill {function_name}: {str(e)}"
                                logger.exception(error_msg)
                                task.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": error_msg,
                                })
                                await self._notify(task, f"Skill {function_name} error: {str(e)}")
                    
                    # Check stop conditions
                    if task.config.stop_conditions:
                        should_stop, reason = await check_stop_conditions(
                            task.config.stop_conditions,
                            task.messages,
                        )
                        if should_stop:
                            task.state = TaskState.COMPLETED
                            await self._notify(task, f"Stop condition met: {reason}")
                            logger.info(f"Task {task.task_id} stopped: {reason}")
                            break
                    
                    # Check if context should be compressed
                    if hasattr(self.context_mgr, 'should_compress') and hasattr(self.context_mgr, 'compress'):
                        if self.context_mgr.should_compress(task.messages):
                            task.messages = await self.context_mgr.compress(task.messages)
                            logger.debug(f"Compressed context for task {task.task_id}")
                
                except Exception as e:
                    logger.exception(f"Error in iteration {task.current_iteration}: {e}")
                    # Add error to messages so LLM can try to recover
                    task.messages.append({
                        "role": "user",
                        "content": f"An error occurred: {str(e)}. Please try a different approach.",
                    })
            
            # Handle max iterations reached
            if (
                task.state == TaskState.RUNNING
                and task.current_iteration >= task.config.max_iterations
            ):
                task.state = TaskState.COMPLETED
                await self._notify(
                    task,
                    f"Reached maximum iterations ({task.config.max_iterations}). Task paused.",
                )
                logger.info(f"Task {task.task_id} reached max iterations")
        
        except Exception as e:
            task.state = TaskState.FAILED
            task.error = str(e)
            logger.exception(f"Task {task.task_id} failed with error: {e}")
            await self._notify(task, f"Task failed: {str(e)}")
        
        finally:
            # Remove from active tasks
            if task.task_id in self.active_tasks:
                del self.active_tasks[task.task_id]
            logger.info(f"Task {task.task_id} finished with state: {task.state}")
    
    def stop_task(self, task_id: str) -> bool:
        """
        Stop a running task by setting its cancel event.
        
        Args:
            task_id: The ID of the task to stop.
        
        Returns:
            bool: True if the task was found and signalled to stop,
                False if the task was not found.
        """
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.cancel_event.set()
            logger.info(f"Signalled task {task_id} to stop")
            return True
        logger.warning(f"Cannot stop task {task_id}: not found in active tasks")
        return False
    
    async def _notify(self, task: AgentTask, message: str) -> None:
        """
        Send a status notification via the callback.
        
        Args:
            task: The task to notify about.
            message: The status message to send.
        """
        if self.status_callback is not None:
            try:
                # Check if callback is a coroutine function
                import inspect
                if inspect.iscoroutinefunction(self.status_callback):
                    await self.status_callback(task.task_id, message)
                else:
                    # Call synchronously if not async
                    self.status_callback(task.task_id, message)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")
