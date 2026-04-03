"""
YAML Skill Loader - Dynamically creates skills from YAML configuration.

This module provides the YAMLSkill class for creating skills from dict configs
and the load_yaml_skills function for loading skills from a YAML file.
"""

import asyncio
import logging
import re
import shlex
from pathlib import Path
from typing import Any

import yaml

from .base import Skill, SkillResult, ToolParameter

logger = logging.getLogger(__name__)

# Regex pattern to match {param_name} or {param_name:default_value}
PLACEHOLDER_PATTERN = re.compile(r'\{(\w+)(?::([^}]*))?\}')


class YAMLSkill(Skill):
    """Skill that dynamically executes shell commands from a YAML config.
    
    This class creates a Skill from a dictionary configuration, allowing
    skills to be defined in YAML files without writing Python code.
    
    Attributes:
        command_template: The shell command template with {param} placeholders.
    """
    
    command_template: str
    
    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize a YAMLSkill from a configuration dictionary.
        
        Args:
            config: Dictionary with keys:
                - name: Skill name (required)
                - description: Human-readable description (required)
                - command_template: Shell command with {param} placeholders (required)
                - parameters: List of parameter dicts (optional)
                - dangerous: Whether skill performs dangerous operations (default: False)
                - timeout: Maximum execution time in seconds (default: 300)
                - slash_command: Optional slash command alias (optional)
        """
        # Parse parameters from config
        parameters = []
        for param_config in config.get('parameters', []):
            param = ToolParameter(
                name=param_config['name'],
                type=param_config.get('type', 'string'),
                description=param_config.get('description', ''),
                required=param_config.get('required', True),
                enum=param_config.get('enum'),
            )
            parameters.append(param)
        
        # Initialize the Skill base class
        super().__init__(
            name=config['name'],
            description=config['description'],
            parameters=parameters,
            dangerous=config.get('dangerous', False),
            timeout=config.get('timeout', 300),
            slash_command=config.get('slash_command'),
        )
        
        # Store the command template
        self.command_template = config['command_template']
    
    def _build_command(self, **kwargs: Any) -> str:
        """Build the shell command by substituting parameters.
        
        Finds all {param_name} and {param_name:default_value} placeholders
        in the command template and substitutes them with provided values
        or defaults. All substituted values are shell-escaped using
        shlex.quote().
        
        Args:
            **kwargs: Parameter values to substitute.
        
        Returns:
            The shell command with all placeholders substituted.
        
        Raises:
            ValueError: If a required parameter is missing and has no default.
        """
        def replace_placeholder(match: re.Match[str]) -> str:
            param_name = match.group(1)
            default_value = match.group(2)  # None if no default specified
            
            if param_name in kwargs:
                value = str(kwargs[param_name])
            elif default_value is not None:
                value = default_value
            else:
                raise ValueError(f"Missing required parameter: {param_name}")
            
            # Shell-escape the value to prevent injection
            return shlex.quote(value)
        
        return PLACEHOLDER_PATTERN.sub(replace_placeholder, self.command_template)
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the skill by running the shell command.
        
        Builds the command from the template, executes it via subprocess,
        and returns the combined output.
        
        Args:
            **kwargs: Parameter values for command substitution.
        
        Returns:
            SkillResult with combined stdout+stderr output (truncated to 4000 chars).
        """
        try:
            # Build the command with parameter substitution
            command = self._build_command(**kwargs)
            logger.debug(f"Executing command: {command}")
            
            # Execute via subprocess
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                # Wait for completion with timeout
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SkillResult(
                    success=False,
                    output=f"Command timed out after {self.timeout} seconds",
                )
            
            # Combine and truncate output
            output_text = ""
            if stdout:
                output_text += stdout.decode('utf-8', errors='replace')
            if stderr:
                if output_text:
                    output_text += "\n"
                output_text += stderr.decode('utf-8', errors='replace')
            
            # Truncate to 4000 characters
            if len(output_text) > 4000:
                output_text = output_text[:3997] + "..."
            
            return SkillResult(
                success=proc.returncode == 0,
                output=output_text or "(no output)",
            )
            
        except ValueError as e:
            return SkillResult(
                success=False,
                output=f"Parameter error: {e}",
            )
        except Exception as e:
            logger.exception(f"Error executing skill {self.name}")
            return SkillResult(
                success=False,
                output=f"Execution error: {e}",
            )


def load_yaml_skills(registry: Any, path: str = "config/skills.yaml") -> int:
    """Load skills from a YAML configuration file.
    
    Reads a YAML file, iterates the "quick_skills" list, creates a YAMLSkill
    for each entry, and registers them with the provided registry.
    
    Args:
        registry: SkillRegistry instance to register skills with.
        path: Path to the YAML configuration file.
            Can be relative or absolute. Defaults to "config/skills.yaml".
    
    Returns:
        Number of skills successfully loaded and registered.
    
    Example YAML structure:
        quick_skills:
          - name: nmap_scan
            description: Run nmap scan on a target
            command_template: "nmap -sV {target}"
            parameters:
              - name: target
                type: string
                description: Target host or IP
            dangerous: false
            timeout: 120
            slash_command: /nmap
    """
    skill_path = Path(path)
    
    if not skill_path.is_absolute():
        # Try relative to current working directory first
        if not skill_path.exists():
            # Try relative to this module's location
            module_dir = Path(__file__).parent.parent
            skill_path = module_dir / path
    
    if not skill_path.exists():
        logger.warning(f"Skills YAML file not found: {path}")
        return 0
    
    try:
        with open(skill_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML file {path}: {e}")
        return 0
    except IOError as e:
        logger.error(f"Failed to read YAML file {path}: {e}")
        return 0
    
    if not config:
        logger.info(f"No configuration found in {path}")
        return 0
    
    quick_skills = config.get('quick_skills', [])
    
    if not quick_skills:
        logger.info(f"No quick_skills defined in {path}")
        return 0
    
    count = 0
    for skill_config in quick_skills:
        try:
            skill = YAMLSkill(skill_config)
            registry.register(skill)
            count += 1
        except KeyError as e:
            logger.error(f"Missing required key in skill config: {e}")
        except Exception as e:
            logger.error(f"Failed to create skill from config: {e}")
    
    logger.info(f"Loaded {count} skills from {path}")
    return count
