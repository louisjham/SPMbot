"""
Formatters - Message formatting utilities for Kali Agent Telegram bot.

This module provides utilities for formatting messages for Telegram,
including MarkdownV2/HTML escaping, code blocks, and message truncation.
"""

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..skills.base import SkillResult
    from ..tasks.models import AgentTask


# HTML special characters that need escaping
HTML_ESCAPE_CHARS = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
}


def escape_html(text: str) -> str:
    """
    Escape special HTML characters in text.
    
    Args:
        text: The text to escape.
    
    Returns:
        The escaped text safe for HTML formatting.
    
    Example:
        >>> escape_html("<script>alert('xss')</script>")
        "<script>alert('xss')</script>"
    """
    for char, escape in HTML_ESCAPE_CHARS.items():
        text = text.replace(char, escape)
    return text


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2 formatting.
    
    MarkdownV2 requires escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    Args:
        text: The text to escape.
    
    Returns:
        The escaped text safe for MarkdownV2 formatting.
    
    Example:
        >>> escape_markdown_v2("Hello *world*!")
        "Hello \\*world\\*\\!"
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def format_code_block(
    code: str,
    language: Optional[str] = None,
    use_html: bool = True,
) -> str:
    """
    Format a code block for Telegram.
    
    Args:
        code: The code content to format.
        language: Optional language identifier for syntax highlighting.
        use_html: If True, use HTML formatting; otherwise use MarkdownV2.
    
    Returns:
        The formatted code block string.
    
    Example:
        >>> format_code_block("print('hello')", "python")
        "<pre><code class=\"language-python\">print('hello')</code></pre>"
    """
    if use_html:
        escaped_code = escape_html(code)
        if language:
            return f'<pre><code class="language-{language}">{escaped_code}</code></pre>'
        return f"<pre><code>{escaped_code}</code></pre>"
    else:
        escaped_code = escape_markdown_v2(code)
        return f"```{language or ''}\n{escaped_code}\n```"


def format_error(error_message: str) -> str:
    """
    Format an error message for display.
    
    Args:
        error_message: The error message to format.
    
    Returns:
        Formatted error message with emoji and styling.
    
    Example:
        >>> format_error("Connection failed")
        "❌ <b>Error:</b>\\n<pre>Connection failed</pre>"
    """
    escaped_message = escape_html(error_message)
    return f"❌ <b>Error:</b>\n<pre>{escaped_message}</pre>"


def format_response(response: str) -> str:
    """
    Format an agent response for Telegram.
    
    Handles basic formatting and ensures the response is safe for HTML.
    
    Args:
        response: The agent response to format.
    
    Returns:
        The formatted response string.
    """
    # Escape HTML to prevent injection
    formatted = escape_html(response)
    
    # Convert markdown-style code blocks to HTML
    # Pattern: ```language\ncode```
    code_block_pattern = r"```(\w*)\n(.*?)```"
    
    def replace_code_block(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2)
        # The code is already HTML-escaped, so we use it directly
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        return f"<pre><code>{code}</code></pre>"
    
    formatted = re.sub(code_block_pattern, replace_code_block, formatted, flags=re.DOTALL)
    
    # Convert inline code: `code` -> <code>code</code>
    inline_code_pattern = r"`([^`]+)`"
    formatted = re.sub(inline_code_pattern, r"<code>\1</code>", formatted)
    
    # Convert markdown bold: **text** -> <b>text</b>
    bold_pattern = r"\*\*([^*]+)\*\*"
    formatted = re.sub(bold_pattern, r"<b>\1</b>", formatted)
    
    # Convert markdown italic: *text* -> <i>text</i>
    italic_pattern = r"\*([^*]+)\*"
    formatted = re.sub(italic_pattern, r"<i>\1</i>", formatted)
    
    return formatted


def format_skill_result(
    skill_name: str,
    output: str,
    success: bool = True,
    execution_time: Optional[float] = None,
) -> str:
    """
    Format a skill execution result for display.
    
    Args:
        skill_name: Name of the executed skill.
        output: The skill output/result.
        success: Whether the skill execution was successful.
        execution_time: Optional execution time in seconds.
    
    Returns:
        Formatted skill result string.
    
    Example:
        >>> format_skill_result("nmap_scan", "Port 80 open", True, 2.5)
        "✅ <b>Skill: nmap_scan</b>\\n<pre>Port 80 open</pre>\\n⏱ Time: 2.50s"
    """
    status_emoji = "✅" if success else "❌"
    escaped_output = escape_html(output)
    
    lines = [
        f"{status_emoji} <b>Skill: {escape_html(skill_name)}</b>",
        f"<pre>{escaped_output}</pre>",
    ]
    
    if execution_time is not None:
        lines.append(f"⏱ Time: {execution_time:.2f}s")
    
    return "\n".join(lines)


def format_history_entry(
    index: int,
    role: str,
    emoji: str,
    content: str,
    timestamp: Optional[datetime] = None,
) -> str:
    """
    Format a single history entry for display.
    
    Args:
        index: The message index number.
        role: The role name (e.g., "You", "Agent").
        emoji: Emoji to prepend.
        content: The message content (should be pre-truncated).
        timestamp: Optional message timestamp.
    
    Returns:
        Formatted history entry string.
    """
    time_str = ""
    if timestamp:
        time_str = f" [{timestamp.strftime('%H:%M')}]"
    
    return (
        f"{emoji} <b>{role}</b>{time_str}\n"
        f"{escape_html(content)}"
    )


def truncate_message(
    text: str,
    max_length: int = 4000,
    overlap: int = 100,
) -> list[str]:
    """
    Split a message into chunks that fit within Telegram's limits.
    
    Telegram has a 4096 character limit for messages. This function
    splits long messages into smaller chunks, trying to break at
    sensible points.
    
    Args:
        text: The text to truncate/split.
        max_length: Maximum length per chunk (default 4000 for safety).
        overlap: Number of characters to overlap between chunks.
    
    Returns:
        List of message chunks.
    
    Example:
        >>> chunks = truncate_message(long_text, max_length=100)
        >>> len(chunks)
        3
    """
    if len(text) <= max_length:
        return [text]
    
    chunks: list[str] = []
    remaining = text
    
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        
        # Find a good break point
        break_point = max_length
        
        # Try to break at paragraph
        paragraph_break = remaining.rfind("\n\n", 0, max_length)
        if paragraph_break > max_length // 2:
            break_point = paragraph_break + 2
        else:
            # Try to break at newline
            newline_break = remaining.rfind("\n", 0, max_length)
            if newline_break > max_length // 2:
                break_point = newline_break + 1
            else:
                # Try to break at space
                space_break = remaining.rfind(" ", 0, max_length)
                if space_break > max_length // 2:
                    break_point = space_break + 1
        
        chunk = remaining[:break_point]
        chunks.append(chunk)
        
        # Move to next chunk with overlap consideration
        remaining = remaining[break_point:]
    
    return chunks


def format_user_info(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> str:
    """
    Format user information for display.
    
    Args:
        user_id: Telegram user ID.
        username: Optional Telegram username.
        first_name: Optional first name.
        last_name: Optional last name.
    
    Returns:
        Formatted user info string.
    """
    parts = [f"ID: <code>{user_id}</code>"]
    
    if username:
        parts.append(f"Username: @{escape_html(username)}")
    
    name_parts = []
    if first_name:
        name_parts.append(first_name)
    if last_name:
        name_parts.append(last_name)
    if name_parts:
        parts.append(f"Name: {escape_html(' '.join(name_parts))}")
    
    return "\n".join(parts)


def format_confirmation_request(
    operation: str,
    risk_level: str = "high",
    details: Optional[str] = None,
) -> str:
    """
    Format a confirmation request for dangerous operations.
    
    Args:
        operation: Description of the operation to be performed.
        risk_level: Risk level indicator (low, medium, high, critical).
        details: Optional additional details about the operation.
    
    Returns:
        Formatted confirmation request string.
    """
    risk_emoji = {
        "low": "⚠️",
        "medium": "🔶",
        "high": "🔴",
        "critical": "🚨",
    }.get(risk_level.lower(), "⚠️")
    
    lines = [
        f"{risk_emoji} <b>Confirmation Required</b>",
        f"Risk Level: <b>{risk_level.upper()}</b>",
        "",
        f"Operation: {escape_html(operation)}",
    ]
    
    if details:
        lines.append("")
        lines.append(f"<pre>{escape_html(details)}</pre>")
    
    lines.extend([
        "",
        "Reply with <b>yes</b> to confirm or <b>no</b> to cancel.",
    ])
    
    return "\n".join(lines)


def format_tool_call(skill_name: str, args: dict) -> str:
    """
    Format a tool/skill call for display.
    
    Args:
        skill_name: Name of the skill being called.
        args: Arguments passed to the skill.
    
    Returns:
        Formatted tool call string with emoji and JSON args.
    
    Example:
        >>> format_tool_call("nmap_scan", {"target": "example.com"})
        "🔧 <b>Running: nmap_scan</b>\\n<pre>{\\"target\\": \\"example.com\\"}</pre>"
    """
    args_json = json.dumps(args, indent=2, default=str)
    return (
        f"🔧 <b>Running: {escape_html(skill_name)}</b>\n"
        f"<pre>{escape_html(args_json)}</pre>"
    )


def format_tool_result(skill_name: str, result: "SkillResult") -> str:
    """
    Format a skill execution result for display.
    
    Args:
        skill_name: Name of the executed skill.
        result: SkillResult object containing output and metadata.
    
    Returns:
        Formatted result string with status, output, artifacts, and hints.
    """
    status_emoji = "✅" if result.success else "❌"
    
    # Truncate output to 3000 chars
    output = result.output
    truncated = False
    if len(output) > 3000:
        output = output[:3000]
        truncated = True
    
    lines = [
        f"{status_emoji} <b>{escape_html(skill_name)}</b>",
        f"<pre>{escape_html(output)}{'... [truncated]' if truncated else ''}</pre>",
    ]
    
    # Add artifacts if present
    if result.artifacts:
        artifact_list = "\n".join(f"  • {escape_html(a)}" for a in result.artifacts)
        lines.append(f"📎 <b>Artifacts:</b>\n{artifact_list}")
    
    # Add follow-up hint if present
    if result.follow_up_hint:
        lines.append(f"💡 <i>{escape_html(result.follow_up_hint)}</i>")
    
    return "\n".join(lines)


def format_task_status(task: "AgentTask") -> str:
    """
    Format an agent task status card for display.
    
    Args:
        task: AgentTask object to format.
    
    Returns:
        Formatted status card with task details.
    """
    goal_truncated = task.config.goal[:100]
    if len(task.config.goal) > 100:
        goal_truncated += "..."
    
    # Format state with emoji
    state_emoji = {
        "pending": "⏳",
        "running": "🔄",
        "waiting_confirmation": "⏸️",
        "paused": "⏸️",
        "completed": "✅",
        "failed": "❌",
        "stopped": "⏹️",
    }.get(task.state.value, "❓")
    
    return (
        f"📋 <b>Task: <code>{escape_html(task.task_id)}</code></b>\n"
        f"{state_emoji} State: <b>{escape_html(task.state.value)}</b>\n"
        f"🔢 Iteration: {task.current_iteration}/{task.config.max_iterations}\n"
        f"🎯 Goal: {escape_html(goal_truncated)}\n"
        f"🕐 Created: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def format_skill_confirmation_request(skill_name: str, args: dict) -> str:
    """
    Format a confirmation request for skill execution.
    
    Args:
        skill_name: Name of the skill to be executed.
        args: Arguments that will be passed to the skill.
    
    Returns:
        Formatted confirmation request with instructions.
    """
    args_json = json.dumps(args, indent=2, default=str)
    return (
        f"⚠️ <b>Confirmation Required</b>\n\n"
        f"Skill: <b>{escape_html(skill_name)}</b>\n"
        f"<pre>{escape_html(args_json)}</pre>\n\n"
        f"Reply with <code>/confirm</code> to proceed or <code>/deny</code> to cancel."
    )


def split_message(text: str, max_length: int = 4000) -> list[str]:
    """
    Split text into chunks at newline boundaries respecting max_length.
    
    Tries to break at paragraph boundaries first, then newlines,
    then spaces, to keep related content together.
    
    Args:
        text: The text to split.
        max_length: Maximum length per chunk (default 4000).
    
    Returns:
        List of text chunks, each within max_length.
    """
    if len(text) <= max_length:
        return [text]
    
    chunks: list[str] = []
    remaining = text
    
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        
        # Find best break point
        break_point = max_length
        
        # Try paragraph break first
        para_break = remaining.rfind("\n\n", 0, max_length)
        if para_break > max_length // 2:
            break_point = para_break + 2
        else:
            # Try newline break
            newline_break = remaining.rfind("\n", 0, max_length)
            if newline_break > max_length // 2:
                break_point = newline_break + 1
            else:
                # Try space break
                space_break = remaining.rfind(" ", 0, max_length)
                if space_break > max_length // 2:
                    break_point = space_break + 1
        
        chunks.append(remaining[:break_point])
        remaining = remaining[break_point:]
    
    return chunks
