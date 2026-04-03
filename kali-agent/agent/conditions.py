"""
Loop Conditions - Termination and control conditions for the agent loop.

This module defines conditions that control when and how the agent loop
should terminate or pause execution.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class LoopCondition(ABC):
    """
    Abstract base class for loop termination conditions.
    
    Conditions determine when the agent loop should stop processing
    or pause for user interaction.
    """
    
    @abstractmethod
    def should_continue(self, context: Any) -> bool:
        """
        Check if the loop should continue processing.
        
        Args:
            context: Current conversation context.
        
        Returns:
            bool: True if the loop should continue, False to stop.
        """
        pass
    
    @abstractmethod
    def reset(self) -> None:
        """Reset the condition to its initial state."""
        pass


class MaxIterationsCondition(LoopCondition):
    """
    Condition that limits the number of loop iterations.
    
    Prevents infinite loops by capping the maximum number of
    iterations the agent can perform.
    """
    
    def __init__(self, max_iterations: int = 10) -> None:
        """
        Initialize the max iterations condition.
        
        Args:
            max_iterations: Maximum number of allowed iterations.
        """
        self.max_iterations = max_iterations
        self._current_iteration = 0
    
    def should_continue(self, context: Any) -> bool:
        """
        Check if we haven't exceeded the maximum iterations.
        
        Args:
            context: Current conversation context (unused).
        
        Returns:
            bool: True if iterations remaining, False if exceeded.
        """
        self._current_iteration += 1
        return self._current_iteration <= self.max_iterations
    
    def reset(self) -> None:
        """Reset the iteration counter."""
        self._current_iteration = 0
    
    @property
    def current_iteration(self) -> int:
        """Get the current iteration number."""
        return self._current_iteration
    
    @property
    def iterations_remaining(self) -> int:
        """Get the number of remaining iterations."""
        return max(0, self.max_iterations - self._current_iteration)


class TimeoutCondition(LoopCondition):
    """
    Condition that limits execution time.
    
    Terminates the loop if execution time exceeds a specified timeout.
    """
    
    def __init__(self, timeout_seconds: float = 300.0) -> None:
        """
        Initialize the timeout condition.
        
        Args:
            timeout_seconds: Maximum execution time in seconds.
        """
        self.timeout_seconds = timeout_seconds
        self._start_time: Optional[float] = None
    
    def should_continue(self, context: Any) -> bool:
        """
        Check if we haven't exceeded the timeout.
        
        Args:
            context: Current conversation context (unused).
        
        Returns:
            bool: True if time remaining, False if exceeded.
        """
        import time
        
        if self._start_time is None:
            self._start_time = time.time()
            return True
        
        elapsed = time.time() - self._start_time
        return elapsed < self.timeout_seconds
    
    def reset(self) -> None:
        """Reset the start time."""
        self._start_time = None


class CompletionKeywordCondition(LoopCondition):
    """
    Condition that checks for completion keywords in responses.
    
    Terminates the loop when specific keywords are detected in
    the LLM's response, indicating task completion.
    """
    
    DEFAULT_KEYWORDS = ["TASK_COMPLETE", "DONE", "FINISHED"]
    
    def __init__(
        self,
        keywords: Optional[list[str]] = None,
        case_sensitive: bool = False,
    ) -> None:
        """
        Initialize the keyword condition.
        
        Args:
            keywords: List of completion keywords to detect.
            case_sensitive: Whether keyword matching is case-sensitive.
        """
        self.keywords = keywords or self.DEFAULT_KEYWORDS
        self.case_sensitive = case_sensitive
        self._last_response: Optional[str] = None
    
    def should_continue(self, context: Any) -> bool:
        """
        Check if no completion keywords were found.
        
        Args:
            context: Current conversation context with messages.
        
        Returns:
            bool: True if no keywords found, False if completion detected.
        """
        # Get the last assistant message
        messages = getattr(context, "messages", [])
        for message in reversed(messages):
            if message.role == "assistant":
                self._last_response = message.content
                break
        
        if self._last_response is None:
            return True
        
        response = self._last_response if self.case_sensitive else self._last_response.lower()
        
        for keyword in self.keywords:
            check_keyword = keyword if self.case_sensitive else keyword.lower()
            if check_keyword in response:
                return False
        
        return True
    
    def reset(self) -> None:
        """Reset the last response."""
        self._last_response = None


class CompositeCondition(LoopCondition):
    """
    Condition that combines multiple conditions with AND/OR logic.
    
    Allows building complex termination conditions from simpler ones.
    """
    
    def __init__(
        self,
        conditions: list[LoopCondition],
        mode: str = "and",
    ) -> None:
        """
        Initialize the composite condition.
        
        Args:
            conditions: List of conditions to combine.
            mode: Combination mode - "and" or "or".
        """
        self.conditions = conditions
        self.mode = mode.lower()
        
        if self.mode not in ("and", "or"):
            raise ValueError(f"Invalid mode '{mode}', must be 'and' or 'or'")
    
    def should_continue(self, context: Any) -> bool:
        """
        Check combined conditions according to the mode.
        
        Args:
            context: Current conversation context.
        
        Returns:
            bool: Combined result of all conditions.
        """
        results = [cond.should_continue(context) for cond in self.conditions]
        
        if self.mode == "and":
            return all(results)
        else:  # mode == "or"
            return any(results)
    
    def reset(self) -> None:
        """Reset all conditions."""
        for condition in self.conditions:
            condition.reset()
