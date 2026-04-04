"""
Agent Prompts - System prompt construction for the Kali Agent.

This module provides constants and functions for building system prompts
that include findings database context and current findings snapshots.
"""

FINDINGS_CONTEXT_BLOCK = """
## Findings Database
After each tool execution, IOCs are automatically extracted and stored.

RULES:
- NEVER fabricate findings. Only reference IPs, domains, ports from actual tool output.
- Cite the source skill when summarizing: "nmap found port 22/tcp open on 10.10.14.3"
- Reference specific finding values when suggesting next steps.
- Do NOT call extract_findings after skills that have auto_extract=True (nmap_scan, web_recon, nuclei_scan, gobuster_enum). Extraction is automatic.
- Prefer HIGH CONFIDENCE findings (>=0.9) for targeting decisions.
- If unsure whether something was discovered, say so rather than guessing.
"""


def build_system_prompt(base_prompt: str, findings_summary: str | None = None) -> str:
    """Build a complete system prompt with findings context.

    Concatenates the base prompt with the findings context block and
    optionally includes a current findings snapshot.

    Args:
        base_prompt: The base system prompt string.
        findings_summary: Optional summary of current findings to include.

    Returns:
        The combined system prompt string.
    """
    prompt = base_prompt + FINDINGS_CONTEXT_BLOCK

    if findings_summary:
        prompt += f"\n## Current Findings Snapshot\n{findings_summary}\n"

    return prompt
