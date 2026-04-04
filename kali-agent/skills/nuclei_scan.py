"""
Nuclei Scan Skill - Vulnerability scanning using Nuclei.

This skill provides a safe interface to Nuclei for detecting
vulnerabilities, misconfigurations, and security issues using
templates.
"""

import asyncio
import shlex
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter


class NucleiScan(Skill):
    """Nuclei vulnerability scanning skill.
    
    Provides safe access to Nuclei for vulnerability detection
    with configurable severity levels and template tags.
    Output is saved to a file for later reference.
    
    Attributes:
        SEVERITY_LEVELS: List of valid severity levels for filtering.
    """
    
    SEVERITY_LEVELS: list[str] = ["info", "low", "medium", "high", "critical"]
    
    def __init__(self):
        super().__init__(
            name="nuclei_scan",
            description=(
                "Perform vulnerability scanning using Nuclei templates. "
                "Detects security issues, misconfigurations, and exposed services "
                "with configurable severity filtering."
            ),
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Target URL, hostname, or IP address to scan (e.g., 'https://example.com')",
                    required=True,
                ),
                ToolParameter(
                    name="severity",
                    type="string",
                    description="Severity levels to include (comma-separated). Default: 'medium,high,critical'",
                    required=False,
                    enum=["info", "low", "medium", "high", "critical"],
                ),
                ToolParameter(
                    name="tags",
                    type="string",
                    description="Template tags to filter (comma-separated, e.g., 'cve,rce,sqli')",
                    required=False,
                ),
            ],
            dangerous=True,
            timeout=600,
            slash_command="/nuclei"
        )
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute a Nuclei vulnerability scan with the specified parameters.
        
        Builds and executes a Nuclei command with the provided target,
        severity filters, and template tags. Output is saved to
        /tmp/nuclei_last.txt for later reference.
        
        Args:
            target: The target URL, hostname, or IP address to scan.
            severity: Comma-separated severity levels to include.
                      Defaults to "medium,high,critical".
            tags: Comma-separated template tags to filter.
        
        Returns:
            SkillResult: Contains truncated scan output, artifact path, and follow-up hints.
        """
        target = kwargs.get("target")
        severity = kwargs.get("severity", "medium,high,critical")
        tags = kwargs.get("tags")
        
        # Validate target exists
        if not target:
            return SkillResult(
                success=False,
                output="Error: No target specified. Please provide a URL, hostname, or IP address to scan.",
                follow_up_hint="Specify a target like 'https://example.com' or 'http://192.168.1.1'.",
            )
        
        # Build the command components
        safe_target = shlex.quote(target)
        safe_severity = shlex.quote(severity)
        
        # Start with base nuclei command
        cmd_parts = ["nuclei"]
        
        # Add target
        cmd_parts.append(f"-u {safe_target}")
        
        # Add severity filter
        cmd_parts.append(f"-severity {safe_severity}")
        
        # Add tags if provided
        if tags:
            safe_tags = shlex.quote(tags)
            cmd_parts.append(f"-tags {safe_tags}")
        
        # Add output file
        output_file = "/tmp/nuclei_last.txt"
        cmd_parts.append(f"-o {shlex.quote(output_file)}")
        
        # Construct full command
        command = " ".join(cmd_parts)
        
        try:
            # Execute the nuclei command
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
                output=f"Error: Nuclei scan timed out after {self.timeout} seconds. Try reducing scope or using specific tags.",
                follow_up_hint="Consider using specific tags to limit template execution.",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                output=f"Error executing nuclei scan: {str(e)}",
                follow_up_hint="Ensure nuclei is installed and templates are updated ('nuclei -update-templates').",
            )
    
    def _build_follow_up_hint(self, output: str) -> str:
        """Build a follow-up hint based on scan results.
        
        Analyzes the Nuclei output to suggest relevant next steps.
        
        Args:
            output: The Nuclei scan output.
        
        Returns:
            str: A hint suggesting follow-up actions.
        """
        hints = []
        output_lower = output.lower()
        
        # Check for critical/high severity findings
        if "critical" in output_lower:
            hints.append("CRITICAL vulnerabilities found - immediate remediation recommended")
        elif "high" in output_lower:
            hints.append("HIGH severity issues detected - prioritize for remediation")
        
        # Check for specific vulnerability types
        if "rce" in output_lower or "remote code execution" in output_lower:
            hints.append("Remote Code Execution detected - urgent patching required")
        
        if "sqli" in output_lower or "sql injection" in output_lower:
            hints.append("SQL Injection found - test for data extraction capabilities")
        
        if "xss" in output_lower or "cross-site scripting" in output_lower:
            hints.append("XSS vulnerability detected - test for session hijacking potential")
        
        if "ssrf" in output_lower or "server-side request forgery" in output_lower:
            hints.append("SSRF found - investigate internal network access potential")
        
        # Check for exposed services
        if "exposed" in output_lower or "misconfiguration" in output_lower:
            hints.append("Misconfigurations detected - review security settings")
        
        # Check for CVE references
        if "cve-" in output_lower:
            hints.append("CVE vulnerabilities identified - check for available patches")
        
        # Check for credentials/secrets
        if "credential" in output_lower or "secret" in output_lower or "api-key" in output_lower:
            hints.append("Exposed credentials detected - immediate rotation recommended")
        
        if hints:
            return "Follow-up suggestions: " + "; ".join(hints[:3])
        else:
            return "No critical vulnerabilities found. Consider expanding scan with lower severity levels."
