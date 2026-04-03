"""
Skill Registry - Registration and discovery system for Kali Agent skills.

This module provides the SkillRegistry class for registering, discovering,
and managing skills that the agent can execute.
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Any, Optional

from .base import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Registry for managing available skills.
    
    Provides skill registration, discovery, and lookup capabilities.
    Supports auto-discovery of skills from a package directory.
    
    Attributes:
        _skills: Dictionary mapping skill name to Skill instance.
        _slash_map: Dictionary mapping slash command to skill name.
    
    Example:
        registry = SkillRegistry()
        registry.auto_discover("skills")
        skill = registry.get("my_skill")
        tools = registry.all_tools()
    """
    
    def __init__(self) -> None:
        """Initialize the skill registry with empty dictionaries."""
        self._skills: dict[str, Skill] = {}
        self._slash_map: dict[str, str] = {}
    
    def register(self, skill: Skill) -> None:
        """
        Register a skill instance.
        
        Adds the skill to both the _skills dict (by name) and _slash_map
        (by slash_command if available).
        
        Args:
            skill: The Skill instance to register.
        
        Raises:
            ValueError: If a skill with the same name is already registered.
        """
        if skill.name in self._skills:
            logger.warning(f"Overwriting existing skill: {skill.name}")
        
        self._skills[skill.name] = skill
        
        if skill.slash_command:
            self._slash_map[skill.slash_command] = skill.name
            logger.debug(f"Mapped slash command {skill.slash_command} -> {skill.name}")
        
        logger.info(f"Registered skill: {skill.name}")
    
    def auto_discover(self, package_path: str = "skills") -> int:
        """
        Auto-discover and register skills from a package directory.
        
        Scans the specified package directory for Python modules, imports
        each module, finds all Skill subclasses (excluding the base class),
        instantiates and registers them.
        
        Skips modules named "base", "registry", or "yaml_loader".
        
        Args:
            package_path: Path to the skills package directory. Can be a
                         dotted module path (e.g., "skills") or a file path.
        
        Returns:
            Number of skills discovered and registered.
        """
        skip_modules = {"base", "registry", "yaml_loader"}
        count = 0
        
        # Try to resolve as a package first
        try:
            package = importlib.import_module(package_path)
            if package.__file__ is None:
                raise AttributeError("Package has no __file__ attribute")
            package_dir = Path(package.__file__).parent
        except (ImportError, AttributeError):
            # Fall back to direct path
            package_dir = Path(package_path)
            if not package_dir.is_dir():
                logger.warning(f"Skills package not found: {package_path}")
                return 0
        
        logger.info(f"Scanning for skills in: {package_dir}")
        
        # Iterate over all modules in the package
        for finder, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
            if module_name in skip_modules:
                logger.debug(f"Skipping module: {module_name}")
                continue
            
            if module_name.startswith("_"):
                logger.debug(f"Skipping private module: {module_name}")
                continue
            
            try:
                # Import the module
                full_module_path = f"{package_path}.{module_name}"
                module = importlib.import_module(full_module_path)
                
                # Find all Skill subclasses in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Check if it's a Skill subclass but not Skill itself
                    if (
                        issubclass(obj, Skill) and
                        obj is not Skill and
                        obj.__module__ == full_module_path
                    ):
                        try:
                            # Instantiate and register the skill
                            skill_instance = obj()
                            self.register(skill_instance)
                            count += 1
                        except Exception as e:
                            logger.error(f"Error instantiating skill {name}: {e}")
            
            except Exception as e:
                logger.error(f"Error loading skill module {module_name}: {e}")
        
        logger.info(f"Discovered {count} skills from {package_path}")
        return count
    
    def get(self, name: str) -> Optional[Skill]:
        """
        Get a skill by name.
        
        Args:
            name: The skill name to look up.
        
        Returns:
            The Skill instance if found, None otherwise.
        """
        return self._skills.get(name)
    
    def get_by_slash(self, command: str) -> Optional[Skill]:
        """
        Get a skill by its slash command.
        
        Args:
            command: The slash command string (e.g., "/scan").
        
        Returns:
            The Skill instance if found, None otherwise.
        """
        skill_name = self._slash_map.get(command)
        if skill_name:
            return self._skills.get(skill_name)
        return None
    
    def all_tools(self) -> list[dict[str, Any]]:
        """
        Get OpenAI tool definitions for all registered skills.
        
        Returns:
            List of OpenAI-compatible tool definition dictionaries.
        """
        tools = []
        for skill in self._skills.values():
            tools.append(skill.to_openai_tool())
        return tools
    
    def all_slash_commands(self) -> dict[str, str]:
        """
        Get all slash commands with their descriptions.
        
        Returns:
            Dictionary mapping slash command to skill description.
            Only includes skills that have a slash_command defined.
        """
        commands = {}
        for command, skill_name in self._slash_map.items():
            skill = self._skills.get(skill_name)
            if skill:
                commands[command] = skill.description
        return commands
    
    def __contains__(self, name: str) -> bool:
        """Check if a skill is registered by name."""
        return name in self._skills
    
    def __len__(self) -> int:
        """Return the number of registered skills."""
        return len(self._skills)
    
    def __iter__(self):
        """Iterate over skill names."""
        return iter(self._skills)
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"SkillRegistry(skills={len(self)}, commands={len(self._slash_map)})"


# Global registry instance for convenience
registry = SkillRegistry()
