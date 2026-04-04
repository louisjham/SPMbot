"""
Finding Extractor Skill - Extracts structured findings from tool output.

This skill parses raw tool output into structured findings using the OutputParser.
It can process text directly or read from files, and extracts entities like
IPs, domains, URLs, open ports, and vulnerabilities.
"""

from dataclasses import asdict
from typing import Any

from skills.base import Skill, SkillResult, ToolParameter
from skills.output_parser import OutputParser


class FindingExtractor(Skill):
    """Extracts structured findings from tool output.

    Parses raw security tool output into structured findings like IPs,
    domains, URLs, open ports, and vulnerabilities. Uses the OutputParser
    to dispatch to tool-specific parsers.
    """

    def __init__(self):
        super().__init__(
            name="extract_findings",
            description=(
                "Extract structured findings from tool output. Parses raw text "
                "from security tools (nmap, gobuster, nuclei, etc.) into "
                "structured entities like IPs, domains, URLs, open ports, and vulnerabilities."
            ),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Raw text output to parse for findings",
                    required=False,
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to file containing tool output to parse",
                    required=False,
                ),
                ToolParameter(
                    name="source_skill",
                    type="string",
                    description="Name of the tool/skill that produced this output (e.g., 'nmap', 'gobuster')",
                    required=False,
                ),
                ToolParameter(
                    name="target",
                    type="string",
                    description="Target host or domain for context (e.g., '192.168.1.1' or 'example.com')",
                    required=False,
                ),
            ],
            dangerous=False,
            timeout=60,
        )

    async def execute(self, **kwargs: Any) -> SkillResult:
        """Extract structured findings from tool output.

        Reads and parses tool output, either from provided text or a file,
        and extracts structured findings like IPs, domains, URLs, ports,
        and vulnerabilities.

        Args:
            text: Raw text output to parse (optional if file_path provided).
            file_path: Path to file containing tool output (optional if text provided).
            source_skill: Name of tool that produced output (helps parser selection).
            target: Target host/domain for context.

        Returns:
            SkillResult: Contains count of extracted findings, the findings list,
                         and a summary by finding type.
        """
        text = kwargs.get("text")
        file_path = kwargs.get("file_path")
        source_skill = kwargs.get("source_skill", "unknown")
        target = kwargs.get("target")

        # Validate that at least text or file_path is provided
        if not text and not file_path:
            return SkillResult(
                success=False,
                output="Error: Either 'text' or 'file_path' must be provided to extract findings.",
                follow_up_hint="Provide raw text output or specify a file path to parse.",
            )

        # Read file if file_path is provided
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    file_contents = f.read()

                # Use file contents as text, appending if text was also provided
                if text:
                    text = f"{text}\n\n{file_contents}"
                else:
                    text = file_contents

            except FileNotFoundError:
                return SkillResult(
                    success=False,
                    output=f"Error: File not found: {file_path}",
                    follow_up_hint="Check the file path and try again.",
                )
            except PermissionError:
                return SkillResult(
                    success=False,
                    output=f"Error: Permission denied reading file: {file_path}",
                    follow_up_hint="Check file permissions and try again.",
                )
            except Exception as e:
                return SkillResult(
                    success=False,
                    output=f"Error reading file {file_path}: {str(e)}",
                    follow_up_hint="Ensure the file exists and is readable.",
                )

        # Validate that we have text to parse
        if not text or not text.strip():
            return SkillResult(
                success=False,
                output="Error: No text content to parse.",
                follow_up_hint="Provide non-empty text output or a file with content.",
            )

        # Instantiate OutputParser and parse the text
        parser = OutputParser()
        findings = parser.parse(text, source_skill, target)

        if not findings:
            return SkillResult(
                success=True,
                output="No findings extracted from the provided output.",
                findings=[],
                raw_data={"source_skill": source_skill, "target": target, "auto_extract": False},
            )

        # Count findings by type
        counts_by_type: dict[str, int] = {}
        for finding in findings:
            finding_type = finding.finding_type
            counts_by_type[finding_type] = counts_by_type.get(finding_type, 0) + 1

        # Format count summary
        count_summary = ", ".join(f"{count} {finding_type}(s)" for finding_type, count in counts_by_type.items())

        # Convert findings to dict for serialization
        findings_list = [asdict(finding) for finding in findings]

        return SkillResult(
            success=True,
            output=f"{len(findings)} findings extracted: {count_summary}",
            findings=findings_list,
            raw_data={
                "source_skill": source_skill,
                "target": target,
                "counts_by_type": counts_by_type,
                "auto_extract": False,  # This IS the extractor, prevent recursion
            },
        )
