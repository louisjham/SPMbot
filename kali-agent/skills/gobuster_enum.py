"""
Gobuster Enumeration Skill - Directory and file brute forcing.

This skill provides a safe interface to gobuster for discovering
hidden directories and files on web servers using wordlist-based attacks.
"""

import asyncio
import shlex
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter


class GobusterEnum(Skill):
    """Gobuster directory enumeration skill.
    
    Provides safe access to gobuster for directory brute forcing
    with configurable wordlists, threads, and file extensions.
    Output is saved to a file for later reference.
    
    Attributes:
        DEFAULT_WORDLIST: Default wordlist path for directory enumeration.
    """
    
    DEFAULT_WORDLIST: str = "/usr/share/wordlists/dirb/common.txt"
    
    name: str = "gobuster_enum"
    description: str = (
        "Perform directory and file brute forcing using gobuster. "
        "Discovers hidden paths and files on web servers using wordlist attacks."
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="url",
            type="string",
            description="Target URL to enumerate (e.g., 'http://example.com' or 'https://target:8080')",
            required=True,
        ),
        ToolParameter(
            name="wordlist",
            type="string",
            description="Path to wordlist for enumeration (default: /usr/share/wordlists/dirb/common.txt)",
            required=False,
        ),
        ToolParameter(
            name="threads",
            type="integer",
            description="Number of concurrent threads (default: 50)",
            required=False,
        ),
        ToolParameter(
            name="extensions",
            type="string",
            description="File extensions to search for (e.g., 'php,html,txt,bak')",
            required=False,
        ),
    ]
    dangerous: bool = True
    timeout: int = 600
    slash_command: str | None = "/dirbrute"
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute a gobuster directory enumeration with the specified parameters.
        
        Builds and executes a gobuster command with the provided URL, wordlist,
        thread count, and file extensions. Output is saved to /tmp/gobuster_last.txt
        for later reference.
        
        Args:
            url: The target URL to enumerate.
            wordlist: Path to the wordlist file. Defaults to dirb common.txt.
            threads: Number of concurrent threads. Defaults to 50.
            extensions: File extensions to search for.
        
        Returns:
            SkillResult: Contains truncated scan output, artifact path, and follow-up hints.
        """
        url = kwargs.get("url")
        wordlist = kwargs.get("wordlist", self.DEFAULT_WORDLIST)
        threads = kwargs.get("threads", 50)
        extensions = kwargs.get("extensions")
        
        # Validate URL exists
        if not url:
            return SkillResult(
                success=False,
                output="Error: No URL specified. Please provide a target URL to enumerate.",
                follow_up_hint="Specify a URL like 'http://example.com' or 'https://target:8080'.",
            )
        
        # Build the command components
        safe_url = shlex.quote(url)
        safe_wordlist = shlex.quote(wordlist)
        
        # Start with base gobuster command
        cmd_parts = [f"gobuster dir -u {safe_url} -w {safe_wordlist}"]
        
        # Add threads
        cmd_parts.append(f"-t {int(threads)}")
        
        # Add extensions if provided
        if extensions:
            safe_extensions = shlex.quote(extensions)
            cmd_parts.append(f"-x {safe_extensions}")
        
        # Add output file
        output_file = "/tmp/gobuster_last.txt"
        cmd_parts.append(f"-o {shlex.quote(output_file)}")
        
        # Construct full command
        command = " ".join(cmd_parts)
        
        try:
            # Execute the gobuster command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )
            
            # Decode output
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            
            # Determine success
            success = process.returncode == 0
            
            # Combine output for display
            full_output = stdout_text
            if stderr_text:
                full_output += f"\n[stderr]\n{stderr_text}"
            
            # Truncate output for display (keep last 2000 chars for context)
            max_display_length = 2000
            if len(full_output) > max_display_length:
                truncated_output = f"...[output truncated, see {output_file} for full results]\n\n"
                truncated_output += full_output[-(max_display_length - 100):]
            else:
                truncated_output = full_output
            
            # Build follow-up hint based on results
            follow_up_hint = self._build_follow_up_hint(stdout_text)
            
            return SkillResult(
                success=success,
                output=truncated_output,
                raw_data={"return_code": process.returncode, "command": command},
                artifacts=[output_file],
                follow_up_hint=follow_up_hint,
            )
            
        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                output=f"Error: Gobuster timed out after {self.timeout} seconds. Try reducing threads or using a smaller wordlist.",
                follow_up_hint="Consider using fewer threads or a more targeted wordlist.",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                output=f"Error executing gobuster: {str(e)}",
                follow_up_hint="Ensure gobuster is installed and the wordlist exists.",
            )
    
    def _build_follow_up_hint(self, output: str) -> str:
        """Build a follow-up hint based on enumeration results.
        
        Analyzes the gobuster output to suggest relevant next steps.
        
        Args:
            output: The gobuster enumeration output.
        
        Returns:
            str: A hint suggesting follow-up actions.
        """
        hints = []
        output_lower = output.lower()
        
        # Check for discovered paths
        if "status:" in output_lower or "200" in output or "301" in output or "302" in output:
            hints.append("Paths discovered - review output for interesting directories and files")
        
        # Check for admin/login pages
        if "admin" in output_lower:
            hints.append("Admin page found - consider credential testing or further enumeration")
        
        # Check for backup files
        if ".bak" in output_lower or ".backup" in output_lower or ".old" in output_lower:
            hints.append("Backup files detected - may contain sensitive information")
        
        # Check for config files
        if "config" in output_lower or ".conf" in output_lower:
            hints.append("Configuration files found - may expose credentials or settings")
        
        # Check for upload directories
        if "upload" in output_lower:
            hints.append("Upload directory discovered - consider file upload vulnerability testing")
        
        # Check for API endpoints
        if "api" in output_lower:
            hints.append("API endpoints found - consider API enumeration and testing")
        
        if hints:
            return "Follow-up suggestions: " + "; ".join(hints[:3])
        else:
            return "No paths discovered. Try different wordlists or extensions."
