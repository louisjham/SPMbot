"""
Skill Base - Base classes and interfaces for Kali Agent skills.

This module defines the base classes that all skills must implement,
providing a consistent interface for skill execution and registration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParameter:
    """Parameter definition for a skill tool.
    
    Attributes:
        name: The parameter name.
        type: The JSON Schema type (e.g., "string", "integer", "boolean").
        description: Human-readable description of the parameter.
        required: Whether this parameter is required. Defaults to True.
        enum: Optional list of allowed values for the parameter.
    """
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass
class SkillResult:
    """Result of a skill execution.

    Attributes:
        success: Whether the skill execution was successful.
        output: Human-readable output string.
        raw_data: Optional raw data returned by the skill.
        artifacts: List of artifact paths or identifiers generated.
        follow_up_hint: Optional hint for follow-up actions.
        auto_extract: Whether findings should be auto-extracted from output.
        findings: Optional list of extracted findings.
    """
    success: bool
    output: str
    raw_data: Any = None
    artifacts: list[str] = field(default_factory=list)
    follow_up_hint: str | None = None
    auto_extract: bool = False
    findings: list[dict] = field(default_factory=list)


@dataclass
class Skill(ABC):
    """Abstract base class for all skills.
    
    All skills must inherit from this class and implement the
    required abstract methods.
    
    Attributes:
        name: The skill name used for identification.
        description: Human-readable description of the skill.
        parameters: List of parameters this skill accepts.
        dangerous: Whether this skill performs dangerous operations.
        timeout: Maximum execution time in seconds.
        slash_command: Optional slash command alias for the skill.
    """
    name: str
    description: str
    parameters: list[ToolParameter]
    dangerous: bool = False
    timeout: int = 300
    slash_command: str | None = None

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert skill to OpenAI function-calling tool schema format.
        
        Returns:
            dict: OpenAI-compatible tool definition with JSON Schema parameters.
        """
        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []
        
        for param in self.parameters:
            prop_schema: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            
            if param.enum is not None:
                prop_schema["enum"] = param.enum
            
            properties[param.name] = prop_schema
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the skill with the given parameters.
        
        Args:
            **kwargs: Skill execution parameters.
        
        Returns:
            SkillResult: Result of the skill execution.
        """
        pass

    async def validate(self, **kwargs: Any) -> bool:
        """Validate skill parameters before execution.
        
        Default implementation returns True. Override to add
        custom validation logic.
        
        Args:
            **kwargs: Parameters to validate.
        
        Returns:
            bool: True if parameters are valid, False otherwise.
        """
        return True
