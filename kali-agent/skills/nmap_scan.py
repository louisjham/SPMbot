"""
Nmap Scan Skill - Network scanning using nmap.

This skill provides a safe interface to nmap with predefined scan profiles
for common use cases like quick reconnaissance, full audits, stealth scans,
vulnerability detection, and UDP scanning.
"""

import asyncio
import shlex
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter


class NmapScan(Skill):
    """Nmap network scanning skill with predefined profiles.
    
    Provides safe access to nmap with various scan types and the ability
    to add custom flags. Output is saved to a file for later reference.
    
    Attributes:
        SCAN_PROFILES: Dictionary mapping scan type names to nmap flag strings.
    """
    
    SCAN_PROFILES: dict[str, str] = {
        "quick": "-sV -T4 --top-ports 1000",
        "full": "-sV -sC -O -p- -T4",
        "stealth": "-sS -T2 -f --data-length 24",
        "vuln": "-sV --script vuln",
        "udp": "-sU -T4 --top-ports 100",
    }
    
    name: str = "nmap_scan"
    description: str = (
        "Perform network scans using nmap with predefined profiles. "
        "Supports quick, full, stealth, vulnerability, and UDP scans."
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="target",
            type="string",
            description="Target host, IP address, or network range to scan (e.g., '192.168.1.1' or 'scanme.nmap.org')",
            required=True,
        ),
        ToolParameter(
            name="scan_type",
            type="string",
            description="Type of scan to perform",
            required=False,
            enum=["quick", "full", "stealth", "vuln", "udp"],
        ),
        ToolParameter(
            name="ports",
            type="string",
            description="Specific ports to scan (e.g., '22,80,443' or '1-1000')",
            required=False,
        ),
        ToolParameter(
            name="additional_flags",
            type="string",
            description="Additional nmap flags to append to the command",
            required=False,
        ),
    ]
    dangerous: bool = True
    timeout: int = 600
    slash_command: str | None = "/scan"
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute an nmap scan with the specified parameters.
        
        Builds and executes an nmap command using the selected scan profile
        along with any optional port specifications and additional flags.
        Output is saved to /tmp/nmap_last.txt for later reference.
        
        Args:
            target: The target host, IP, or network range to scan.
            scan_type: Type of scan (quick, full, stealth, vuln, udp). Defaults to "quick".
            ports: Optional specific ports to scan.
            additional_flags: Optional additional nmap flags.
        
        Returns:
            SkillResult: Contains truncated scan output, artifact path, and follow-up hints.
        """
        target = kwargs.get("target")
        scan_type = kwargs.get("scan_type", "quick")
        ports = kwargs.get("ports")
        additional_flags = kwargs.get("additional_flags")
        
        # Validate target exists
        if not target:
            return SkillResult(
                success=False,
                output="Error: No target specified. Please provide a host, IP, or network range to scan.",
                follow_up_hint="Specify a target like '192.168.1.1' or 'scanme.nmap.org'.",
            )
        
        # Get the base profile flags
        profile_flags = self.SCAN_PROFILES.get(scan_type, self.SCAN_PROFILES["quick"])
        
        # Build the command components
        safe_target = shlex.quote(target)
        
        # Start with base nmap command and profile
        cmd_parts = [f"nmap {profile_flags}"]
        
        # Add port specification if provided
        if ports:
            safe_ports = shlex.quote(ports)
            cmd_parts.append(f"-p {safe_ports}")
        
        # Add additional flags if provided
        if additional_flags:
            cmd_parts.append(additional_flags)
        
        # Add output file and target
        output_file = "/tmp/nmap_last.txt"
        cmd_parts.append(f"-oN {shlex.quote(output_file)}")
        cmd_parts.append(safe_target)
        
        # Construct full command
        command = " ".join(cmd_parts)
        
        try:
            # Execute the nmap command
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
            
            # Build follow-up hint based on scan results
            follow_up_hint = self._build_follow_up_hint(stdout_text, scan_type)
            
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
                output=f"Error: Scan timed out after {self.timeout} seconds. Try using a quicker scan type or reducing the port range.",
                follow_up_hint="Consider using 'quick' scan type or specifying fewer ports.",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                output=f"Error executing nmap scan: {str(e)}",
                follow_up_hint="Ensure nmap is installed and you have proper permissions.",
            )
    
    def _build_follow_up_hint(self, output: str, scan_type: str) -> str:
        """Build a follow-up hint based on scan results.
        
        Analyzes the scan output to suggest relevant next steps.
        
        Args:
            output: The nmap scan output.
            scan_type: The type of scan that was performed.
        
        Returns:
            str: A hint suggesting follow-up actions.
        """
        hints = []
        output_lower = output.lower()
        
        # Check for common services and suggest specific scans
        if "ssh" in output_lower and "22/tcp" in output_lower:
            hints.append("SSH detected on port 22 - consider SSH brute force or key analysis")
        
        if "http" in output_lower or "80/tcp" in output_lower or "443/tcp" in output_lower:
            hints.append("Web services detected - consider web vulnerability scanning (nikto, dirb)")
        
        if "smb" in output_lower or "445/tcp" in output_lower or "139/tcp" in output_lower:
            hints.append("SMB detected - consider enum4linux or smbclient for share enumeration")
        
        if "mysql" in output_lower or "3306/tcp" in output_lower:
            hints.append("MySQL detected - consider database enumeration")
        
        if "ftp" in output_lower and "21/tcp" in output_lower:
            hints.append("FTP detected - consider anonymous login check or brute force")
        
        if "rdp" in output_lower or "3389/tcp" in output_lower:
            hints.append("RDP detected - consider credential testing")
        
        # Suggest vulnerability scan if not already done
        if scan_type != "vuln" and ("open" in output_lower or "filtered" in output_lower):
            hints.append("Run 'vuln' scan type to check for known vulnerabilities")
        
        if hints:
            return "Follow-up suggestions: " + "; ".join(hints[:3])
        else:
            return "No obvious follow-up actions. Consider trying a different scan type or manual enumeration."
