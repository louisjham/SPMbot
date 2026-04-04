"""
Agent Configuration - Temperature and behavior settings for the Kali Agent.

This module provides configuration for different phases of agent execution,
allowing fine-tuned control over LLM temperature based on the context.
"""

from typing import Literal

# Temperature mapping for different phases of agent execution
# Lower temperatures = more deterministic, higher = more creative
TEMPERATURE_MAP: dict[str, float] = {
    "tool_call": 0.1,           # Very low for precise tool selection
    "tool_params": 0.0,         # Zero for exact parameter formatting
    "planning": 0.7,            # Higher for strategic thinking
    "summarize": 0.5,           # Moderate for balanced summaries
    "structured_output": 0.0,   # Zero for consistent JSON/structured output
    "default": 0.4,             # Default balanced temperature
}

PhaseType = Literal[
    "tool_call",
    "tool_params",
    "planning",
    "summarize",
    "structured_output",
    "default",
]


def get_temperature(phase: PhaseType) -> float:
    """Get the temperature setting for a given phase.

    Args:
        phase: The execution phase name.

    Returns:
        The temperature value for the phase, or default if phase not found.
    """
    return TEMPERATURE_MAP.get(phase, TEMPERATURE_MAP["default"])
