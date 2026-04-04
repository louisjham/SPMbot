"""
Guardrails - Validates agent responses against findings database.

This module provides guardrail functionality to check if the agent is
referencing IPs, ports, or CVEs that haven't been discovered yet.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.context_manager import FindingsContext


class FindingsGuardrail:
    """Validates agent responses against discovered findings.

    Checks if the agent is referencing IPs, ports, or CVEs that haven't
    been discovered in the current session, helping prevent hallucination.
    """

    WHITELIST = {"0.0.0.0", "127.0.0.1", "255.255.255.255", "::1", "localhost"}

    def __init__(self, findings_context: "FindingsContext") -> None:
        """Initialize the guardrail with a findings context.

        Args:
            findings_context: The FindingsContext containing discovered findings.
        """
        self.findings_context = findings_context

    def check_response(self, response_text: str) -> list[dict]:
        """Check response text for unverified references.

        Extracts all IPv4 addresses, port references (N/tcp, N/udp), and CVE IDs
        from natural language text (excluding code blocks), and checks if they
        have been discovered or are in the whitelist.

        Args:
            response_text: The agent's response text to check.

        Returns:
            List of dicts with unverified references: {"value": value, "pattern_type": type}.
            Returns empty list if all references are verified.
        """
        # Split on code blocks and only check non-code sections
        text_to_check = self._extract_non_code_text(response_text)

        # Get all known values from findings and whitelist
        known_values = self.findings_context.get_all_values() | self.WHITELIST

        warnings = []
        seen_values = set()

        # Extract and check IPv4 addresses
        ipv4_pattern = r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
        for match in re.finditer(ipv4_pattern, text_to_check):
            ip = match.group(1)
            if ip not in known_values and ip not in seen_values:
                seen_values.add(ip)
                warnings.append({"value": ip, "pattern_type": "ipv4"})

        # Extract and check port references (N/tcp or N/udp)
        port_pattern = r"\b(\d{1,5})/(tcp|udp)\b"
        for match in re.finditer(port_pattern, text_to_check):
            port_proto = match.group(0)
            if port_proto not in known_values and port_proto not in seen_values:
                seen_values.add(port_proto)
                warnings.append({"value": port_proto, "pattern_type": "port"})

        # Extract and check CVE IDs
        cve_pattern = r"\b(CVE-\d{4}-\d+)\b"
        for match in re.finditer(cve_pattern, text_to_check):
            cve = match.group(0)
            if cve not in known_values and cve not in seen_values:
                seen_values.add(cve)
                warnings.append({"value": cve, "pattern_type": "cve"})

        return warnings

    def annotate(self, response_text: str) -> tuple[str, list[dict]]:
        """Annotate response with warnings if unverified references are found.

        Args:
            response_text: The agent's response text to check and possibly annotate.

        Returns:
            A tuple of (annotated_text, warnings). If warnings are found,
            an annotation is appended to the text.
        """
        warnings = self.check_response(response_text)

        if warnings:
            # Extract values for the warning message
            values = [w["value"] for w in warnings]
            warning_message = f"\n\n⚠️ Unverified references: {', '.join(values)}. Cross-check before acting."
            annotated_text = response_text + warning_message
            return annotated_text, warnings

        return response_text, warnings

    def _extract_non_code_text(self, text: str) -> str:
        """Extract non-code text sections, skipping fenced code blocks.

        Splits text on ``` blocks and returns only the non-code sections.

        Args:
            text: The text to process.

        Returns:
            Text with code blocks removed.
        """
        # Split on ``` and take only even-indexed sections (non-code)
        sections = text.split("```")
        non_code_sections = sections[::2]  # Take every other section starting from 0
        return "".join(non_code_sections)
