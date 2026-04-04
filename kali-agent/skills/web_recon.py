"""
Web Reconnaissance Skill - Comprehensive web target reconnaissance.

This skill provides a safe interface to gather information about web targets
using multiple reconnaissance tools in sequence, with light and deep modes.
"""

import asyncio
import shlex
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter


class WebRecon(Skill):
    """Web reconnaissance skill with light and deep modes.
    
    Provides comprehensive reconnaissance by running multiple tools
    in sequence. Light mode uses whois, dig, and curl for basic
    information gathering. Deep mode adds subfinder and httpx for
    subdomain enumeration and live host detection.
    
    Attributes:
        RECON_DEPTH: List of valid depth levels for reconnaissance.
    """
    
    RECON_DEPTH: list[str] = ["light", "deep"]
    
    def __init__(self):
        super().__init__(
            name="web_recon",
            description=(
                "Perform web reconnaissance on a target domain. "
                "Light mode runs whois, dig, and curl for basic info. "
                "Deep mode adds subfinder and httpx for comprehensive enumeration."
            ),
            parameters=[
                ToolParameter(
                    name="domain",
                    type="string",
                    description="Target domain to investigate (e.g., 'example.com')",
                    required=True,
                ),
                ToolParameter(
                    name="depth",
                    type="string",
                    description="Reconnaissance depth: 'light' for basic (whois, dig, curl) or 'deep' for full (adds subfinder, httpx)",
                    required=False,
                    enum=["light", "deep"],
                ),
            ],
            dangerous=False,
            timeout=600,
            slash_command="/recon"
        )
    
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute web reconnaissance with the specified parameters.
        
        Runs multiple reconnaissance tools in sequence based on the
        selected depth level. Aggregates all outputs into a combined
        result.
        
        Args:
            domain: The target domain to investigate.
            depth: Reconnaissance depth level. Defaults to "light".
                   - light: whois, dig, curl -sI
                   - deep: light + subfinder, httpx
        
        Returns:
            SkillResult: Contains aggregated output from all tools and follow-up hints.
        """
        domain = kwargs.get("domain")
        depth = kwargs.get("depth", "light")
        
        # Validate domain exists
        if not domain:
            return SkillResult(
                success=False,
                output="Error: No domain specified. Please provide a target domain to investigate.",
                follow_up_hint="Specify a domain like 'example.com'.",
            )
        
        # Validate depth
        if depth not in self.RECON_DEPTH:
            depth = "light"
        
        # Sanitize domain
        safe_domain = shlex.quote(domain)
        
        # Collect results from each tool
        results: dict[str, str] = {}
        errors: list[str] = []
        artifacts: list[str] = []
        
        try:
            # Run whois
            whois_result = await self._run_command(
                f"whois {safe_domain}",
                "whois",
                timeout=60,
            )
            results["whois"] = whois_result["output"]
            if not whois_result["success"]:
                errors.append(f"whois: {whois_result['error']}")
            
            # Run dig
            dig_result = await self._run_command(
                f"dig +short {safe_domain} ANY",
                "dig",
                timeout=30,
            )
            results["dig"] = dig_result["output"]
            if not dig_result["success"]:
                errors.append(f"dig: {dig_result['error']}")
            
            # Run curl for HTTP headers
            curl_result = await self._run_command(
                f"curl -sI {safe_domain}",
                "curl",
                timeout=30,
            )
            results["curl_headers"] = curl_result["output"]
            if not curl_result["success"]:
                errors.append(f"curl: {curl_result['error']}")
            
            # Deep mode: add subfinder and httpx
            if depth == "deep":
                # Run subfinder for subdomain enumeration
                subfinder_result = await self._run_command(
                    f"subfinder -d {safe_domain} -silent",
                    "subfinder",
                    timeout=120,
                )
                results["subfinder"] = subfinder_result["output"]
                if not subfinder_result["success"]:
                    errors.append(f"subfinder: {subfinder_result['error']}")
                
                # Run httpx for live host detection on found subdomains
                if subfinder_result["output"].strip():
                    # Write subdomains to temp file for httpx
                    subdomains_file = "/tmp/recon_subdomains.txt"
                    httpx_result = await self._run_command(
                        f"subfinder -d {safe_domain} -silent | httpx -silent -status-code -title",
                        "httpx",
                        timeout=180,
                    )
                    results["httpx"] = httpx_result["output"]
                    if not httpx_result["success"]:
                        errors.append(f"httpx: {httpx_result['error']}")
                    artifacts.append(subdomains_file)
            
            # Aggregate all outputs
            aggregated_output = self._format_aggregated_output(domain, depth, results, errors)
            
            # Save aggregated output to file
            output_file = "/tmp/recon_last.txt"
            try:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(aggregated_output)
                artifacts.append(output_file)
            except IOError:
                pass  # Continue without artifact file if write fails
            
            # Build follow-up hint
            follow_up_hint = self._build_follow_up_hint(results, depth)
            
            return SkillResult(
                success=len(errors) == 0,
                output=self._truncate_output(aggregated_output),
                raw_data={"depth": depth, "tools_run": list(results.keys()), "errors": errors},
                artifacts=artifacts,
                follow_up_hint=follow_up_hint,
            )
            
        except asyncio.TimeoutError:
            return SkillResult(
                success=False,
                output=f"Error: Reconnaissance timed out after {self.timeout} seconds.",
                follow_up_hint="Try using 'light' depth mode for faster results.",
            )
        except Exception as e:
            return SkillResult(
                success=False,
                output=f"Error during reconnaissance: {str(e)}",
                follow_up_hint="Ensure required tools (whois, dig, curl) are installed.",
            )
    
    async def _run_command(
        self, command: str, tool_name: str, timeout: int = 60
    ) -> dict[str, Any]:
        """Run a single command and return the result.
        
        Args:
            command: The command to execute.
            tool_name: Name of the tool for error reporting.
            timeout: Maximum execution time in seconds.
        
        Returns:
            dict: Contains 'success', 'output', and 'error' keys.
        """
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            
            return {
                "success": process.returncode == 0,
                "output": stdout_text.strip(),
                "error": stderr_text.strip() if stderr_text else None,
            }
            
        except asyncio.TimeoutError:
            return {
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout}s",
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
            }
    
    def _format_aggregated_output(
        self,
        domain: str,
        depth: str,
        results: dict[str, str],
        errors: list[str],
    ) -> str:
        """Format aggregated results into a single output string.
        
        Args:
            domain: The target domain.
            depth: The reconnaissance depth level.
            results: Dictionary of tool results.
            errors: List of error messages.
        
        Returns:
            str: Formatted aggregated output.
        """
        sections = [
            f"{'=' * 60}",
            f"WEB RECONNAISSANCE REPORT",
            f"{'=' * 60}",
            f"Target: {domain}",
            f"Depth: {depth.upper()}",
            f"{'=' * 60}\n",
        ]
        
        # WHOIS section
        if results.get("whois"):
            sections.extend([
                "--- WHOIS Information ---",
                results["whois"][:1500] + ("..." if len(results["whois"]) > 1500 else ""),
                "",
            ])
        
        # DNS section
        if results.get("dig"):
            sections.extend([
                "--- DNS Records (dig) ---",
                results["dig"] or "No records found",
                "",
            ])
        
        # HTTP Headers section
        if results.get("curl_headers"):
            sections.extend([
                "--- HTTP Headers ---",
                results["curl_headers"],
                "",
            ])
        
        # Deep mode additions
        if depth == "deep":
            if results.get("subfinder"):
                sections.extend([
                    "--- Subdomains (subfinder) ---",
                    results["subfinder"] or "No subdomains found",
                    "",
                ])
            
            if results.get("httpx"):
                sections.extend([
                    "--- Live Hosts (httpx) ---",
                    results["httpx"] or "No live hosts detected",
                    "",
                ])
        
        # Errors section
        if errors:
            sections.extend([
                "--- Errors ---",
                "\n".join(errors),
                "",
            ])
        
        sections.append(f"{'=' * 60}")
        
        return "\n".join(sections)
    
    def _truncate_output(self, output: str, max_length: int = 3000) -> str:
        """Truncate output if it exceeds maximum length.
        
        Args:
            output: The output string to truncate.
            max_length: Maximum allowed length.
        
        Returns:
            str: Truncated output with indicator if truncated.
        """
        if len(output) <= max_length:
            return output
        
        return (
            f"...[output truncated, see /tmp/recon_last.txt for full results]\n\n"
            + output[-(max_length - 100):]
        )
    
    def _build_follow_up_hint(self, results: dict[str, str], depth: str) -> str:
        """Build a follow-up hint based on reconnaissance results.
        
        Analyzes the gathered information to suggest relevant next steps.
        
        Args:
            results: Dictionary of tool results.
            depth: The reconnaissance depth level.
        
        Returns:
            str: A hint suggesting follow-up actions.
        """
        hints = []
        
        # Check DNS results
        dig_output = results.get("dig", "").lower()
        if dig_output and len(dig_output.split("\n")) > 3:
            hints.append("Multiple DNS records found - investigate each for potential vulnerabilities")
        
        # Check HTTP headers
        curl_output = results.get("curl_headers", "").lower()
        if "server:" in curl_output:
            hints.append("Server header exposed - research for known vulnerabilities")
        if "x-frame-options" not in curl_output:
            hints.append("Missing X-Frame-Options - potential clickjacking vulnerability")
        if "strict-transport-security" not in curl_output:
            hints.append("Missing HSTS header - consider HTTPS enforcement")
        
        # Check subdomains (deep mode)
        if depth == "deep":
            subfinder_output = results.get("subfinder", "")
            if subfinder_output:
                subdomain_count = len(subfinder_output.strip().split("\n"))
                if subdomain_count > 5:
                    hints.append(f"Found {subdomain_count} subdomains - prioritize interesting targets for further testing")
            
            httpx_output = results.get("httpx", "")
            if httpx_output:
                hints.append("Live hosts identified - proceed with vulnerability scanning")
        
        # Check WHOIS for registration info
        whois_output = results.get("whois", "").lower()
        if "registrar" in whois_output:
            hints.append("WHOIS data available - check for social engineering opportunities")
        
        # Suggest deep mode if only light was run
        if depth == "light":
            hints.append("Run with depth='deep' for subdomain enumeration and live host detection")
        
        if hints:
            return "Follow-up suggestions: " + "; ".join(hints[:3])
        else:
            return "Reconnaissance complete. Consider targeted vulnerability scanning based on findings."
