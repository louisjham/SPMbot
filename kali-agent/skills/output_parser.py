"""
Output Parser - Parses tool outputs into structured findings.

This module provides tool-specific parsers that extract structured findings
from raw command output, supporting nmap, dig, gobuster, nuclei, and generic parsing.
"""

from dataclasses import dataclass, field
import re
from typing import Callable


@dataclass
class ParsedFinding:
    """Represents a parsed finding from tool output.
    
    Attributes:
        finding_type: Type of finding (e.g., "open_port", "ip", "domain", "url", "vulnerability").
        value: The main value of the finding.
        target: Optional target associated with this finding.
        context: Additional context as key-value pairs.
        confidence: Confidence level of the finding (0.0 to 1.0).
        source_line: Optional original line from which this finding was extracted.
    """
    finding_type: str
    value: str
    target: str | None
    context: dict = field(default_factory=dict)
    confidence: float = 1.0
    source_line: str | None = None


class OutputParser:
    """Parses tool outputs into structured findings.
    
    Dispatches to tool-specific parsers based on tool_name.
    All parsers return list[ParsedFinding] and never raise exceptions.
    """
    
    # Valid TLDs for domain validation
    VALID_TLDS: set[str] = {
        # Common TLDs
        "com", "net", "org", "io", "gov", "edu", "mil", "co",
        # Two-letter country codes (ISO 3166-1 alpha-2)
        "ad", "ae", "af", "ag", "ai", "al", "am", "ao", "aq", "ar", "as", "at", "au",
        "aw", "ax", "az", "ba", "bb", "bd", "be", "bf", "bg", "bh", "bi", "bj", "bl",
        "bm", "bn", "bo", "bq", "br", "bs", "bt", "bv", "bw", "by", "bz", "ca", "cc",
        "cd", "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "cr", "cu", "cv", "cw",
        "cx", "cy", "cz", "de", "dj", "dk", "dm", "do", "dz", "ec", "ee", "eg", "eh",
        "er", "es", "et", "fi", "fj", "fk", "fm", "fo", "fr", "ga", "gb", "gd", "ge",
        "gf", "gg", "gh", "gi", "gl", "gm", "gn", "gp", "gq", "gr", "gs", "gt", "gu",
        "gw", "gy", "hk", "hm", "hn", "hr", "ht", "hu", "id", "ie", "il", "im", "in",
        "io", "iq", "ir", "is", "it", "je", "jm", "jo", "jp", "ke", "kg", "kh", "ki",
        "km", "kn", "kp", "kr", "kw", "ky", "kz", "la", "lb", "lc", "li", "lk", "lr",
        "ls", "lt", "lu", "lv", "ly", "ma", "mc", "md", "me", "mf", "mg", "mh", "mk",
        "ml", "mm", "mn", "mo", "mp", "mq", "mr", "ms", "mt", "mu", "mv", "mw", "mx",
        "my", "mz", "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr", "nu",
        "nz", "om", "pa", "pe", "pf", "pg", "ph", "pk", "pl", "pm", "pn", "pr", "ps",
        "pt", "pw", "py", "qa", "re", "ro", "rs", "ru", "rw", "sa", "sb", "sc", "sd",
        "se", "sg", "sh", "si", "sj", "sk", "sl", "sm", "sn", "so", "sr", "ss", "st",
        "sv", "sx", "sy", "sz", "tc", "td", "tf", "tg", "th", "tj", "tk", "tl", "tm",
        "tn", "to", "tr", "tt", "tv", "tw", "tz", "ua", "ug", "um", "us", "uy", "uz",
        "va", "vc", "ve", "vg", "vi", "vn", "vu", "wf", "ws", "ye", "yt", "za", "zm",
        "zw",
    }
    
    # File extensions to exclude from domain detection
    FILE_EXTENSIONS: set[str] = {
        ".py", ".js", ".json", ".xml", ".txt", ".log", ".conf", ".cfg", ".html", ".css",
    }
    
    def __init__(self) -> None:
        """Initialize the parser with tool-specific parser dispatch."""
        self._parsers: dict[str, Callable[[str, str | None], list[ParsedFinding]]] = {
            "nmap": self._parse_nmap,
            "dig": self._parse_dig,
            "gobuster": self._parse_gobuster,
            "nuclei": self._parse_nuclei,
        }
    
    def parse(self, output: str, tool_name: str, target: str | None = None) -> list[ParsedFinding]:
        """Parse tool output into structured findings.
        
        Args:
            output: Raw tool output string.
            tool_name: Name of the tool that produced the output.
            target: Optional target associated with this output.
            
        Returns:
            List of ParsedFinding objects. Returns empty list on bad input or errors.
        """
        if not output or not isinstance(output, str):
            return []
        
        if not tool_name or not isinstance(tool_name, str):
            return []
        
        tool_name_lower = tool_name.lower()
        parser = self._parsers.get(tool_name_lower, self._generic_parse)
        
        try:
            return parser(output, target)
        except Exception:
            # Never raise - return empty list on any error
            return []
    
    def _parse_nmap(self, output: str, target: str | None) -> list[ParsedFinding]:
        """Parse nmap output for open ports and host information.
        
        Matches patterns like:
        - "22/tcp   open  ssh"
        - "443/udp  open  https"
        - "Nmap scan report for 192.168.1.1"
        
        Args:
            output: Raw nmap output.
            target: Optional target override.
            
        Returns:
            List of ParsedFinding objects for open ports.
        """
        findings: list[ParsedFinding] = []
        
        # Extract host IP from "Nmap scan report for X.X.X.X" lines
        detected_target = target
        host_pattern = re.compile(r"Nmap scan report for\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
        host_match = host_pattern.search(output)
        if host_match and not target:
            detected_target = host_match.group(1)
        
        # Match open ports: "22/tcp   open  ssh"
        port_pattern = re.compile(r"(\d+)/(tcp|udp)\s+open\s+(\S+)")
        
        for match in port_pattern.finditer(output):
            port = match.group(1)
            proto = match.group(2)
            service = match.group(3)
            
            findings.append(ParsedFinding(
                finding_type="open_port",
                value=f"{port}/{proto}",
                target=detected_target,
                context={"service": service},
                confidence=1.0,
                source_line=match.group(0),
            ))
        
        return findings
    
    def _parse_dig(self, output: str, target: str | None) -> list[ParsedFinding]:
        """Parse dig output for IP addresses and domains.
        
        Matches:
        - Bare IPv4 addresses as "ip" findings
        - CNAME/domain formats as "domain" findings
        
        Args:
            output: Raw dig output.
            target: Optional target associated with this output.
            
        Returns:
            List of ParsedFinding objects for IPs and domains.
        """
        findings: list[ParsedFinding] = []
        seen: set[str] = set()
        
        # IPv4 pattern
        ipv4_pattern = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
        
        # Domain/CNAME pattern (in answer section)
        # Matches patterns like "example.com. IN A 1.2.3.4" or "alias.example.com. IN CNAME target.example.com."
        domain_pattern = re.compile(r"\b([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b\.?")
        
        lines = output.split("\n")
        
        for line in lines:
            # Skip empty lines and comments
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith(";") or line_stripped.startswith("<<>>"):
                continue
            
            # Extract IPv4 addresses
            for match in ipv4_pattern.finditer(line):
                ip = match.group(1)
                if ip not in seen and not self._is_private_ip(ip):
                    seen.add(ip)
                    findings.append(ParsedFinding(
                        finding_type="ip",
                        value=ip,
                        target=target,
                        context={},
                        confidence=1.0,
                        source_line=line_stripped,
                    ))
            
            # Extract domains (in answer section, after "ANSWER SECTION")
            if "ANSWER SECTION" in line.upper():
                continue
            
            for match in domain_pattern.finditer(line):
                domain = match.group(0).rstrip(".")
                if domain not in seen and self._is_valid_domain(domain):
                    seen.add(domain)
                    findings.append(ParsedFinding(
                        finding_type="domain",
                        value=domain,
                        target=target,
                        context={},
                        confidence=1.0,
                        source_line=line_stripped,
                    ))
        
        return findings
    
    def _parse_gobuster(self, output: str, target: str | None) -> list[ParsedFinding]:
        """Parse gobuster output for URLs with status codes.
        
        Matches patterns like:
        - "/admin                (Status: 200)"
        - "/api/v1               (Status: 403)"
        
        Skips 404 status codes.
        
        Args:
            output: Raw gobuster output.
            target: Optional target associated with this output.
            
        Returns:
            List of ParsedFinding objects for URLs (excluding 404s).
        """
        findings: list[ParsedFinding] = []
        
        # Match: "/path (Status: 200)"
        url_pattern = re.compile(r"\/(\S+)\s+\(Status:\s*(\d+)\)")
        
        for match in url_pattern.finditer(output):
            path = "/" + match.group(1)
            status_code = int(match.group(2))
            
            # Skip 404s
            if status_code == 404:
                continue
            
            # Build full URL if target is available
            value = f"{target}{path}" if target else path
            
            findings.append(ParsedFinding(
                finding_type="url",
                value=value,
                target=target,
                context={"status_code": status_code},
                confidence=1.0,
                source_line=match.group(0),
            ))
        
        return findings
    
    def _parse_nuclei(self, output: str, target: str | None) -> list[ParsedFinding]:
        """Parse nuclei output for vulnerabilities.
        
        Matches patterns like:
        - "[cve-2021-44228] [critical] https://example.com/vulnerable"
        - "[xss-reflected] [medium] https://example.com/search?q=test"
        
        Args:
            output: Raw nuclei output.
            target: Optional target associated with this output.
            
        Returns:
            List of ParsedFinding objects for vulnerabilities.
        """
        findings: list[ParsedFinding] = []
        
        # Match: "[template-id] [severity] url"
        # Pattern: r'$$(\S+)$$\s+$$(\w+)$$\s+(.+)'
        vuln_pattern = re.compile(r"\[(\S+)\]\s+\[(\w+)\]\s+(.+)")
        
        for match in vuln_pattern.finditer(output):
            template_id = match.group(1)
            severity = match.group(2).lower()
            url = match.group(3).strip()
            
            findings.append(ParsedFinding(
                finding_type="vulnerability",
                value=template_id,
                target=target,
                context={"severity": severity, "matched": url},
                confidence=1.0,
                source_line=match.group(0),
            ))
        
        return findings
    
    def _generic_parse(self, output: str, target: str | None) -> list[ParsedFinding]:
        """Generic parser for unknown tool outputs.
        
        Extracts:
        - IPv4 addresses
        - Domains (validated against TLD list, excluding file-like patterns)
        - URLs
        
        Sets confidence=0.7 for generic extractions.
        
        Args:
            output: Raw tool output.
            target: Optional target associated with this output.
            
        Returns:
            List of ParsedFinding objects with 0.7 confidence.
        """
        findings: list[ParsedFinding] = []
        seen: set[str] = set()
        
        # IPv4 pattern
        ipv4_pattern = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
        
        # URL pattern
        url_pattern = re.compile(r"\b(https?://[^\s<>\"]+)")
        
        # Domain pattern
        domain_pattern = re.compile(r"\b([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b")
        
        # Extract URLs first (highest priority)
        for match in url_pattern.finditer(output):
            url = match.group(1)
            if url not in seen:
                seen.add(url)
                findings.append(ParsedFinding(
                    finding_type="url",
                    value=url,
                    target=target,
                    context={},
                    confidence=0.7,
                    source_line=match.group(0),
                ))
        
        # Extract IPv4 addresses
        for match in ipv4_pattern.finditer(output):
            ip = match.group(1)
            if ip not in seen:
                seen.add(ip)
                findings.append(ParsedFinding(
                    finding_type="ip",
                    value=ip,
                    target=target,
                    context={},
                    confidence=0.7,
                    source_line=match.group(0),
                ))
        
        # Extract domains
        for match in domain_pattern.finditer(output):
            domain = match.group(0)
            if domain not in seen and self._is_valid_domain(domain):
                seen.add(domain)
                findings.append(ParsedFinding(
                    finding_type="domain",
                    value=domain,
                    target=target,
                    context={},
                    confidence=0.7,
                    source_line=match.group(0),
                ))
        
        return findings
    
    def _is_valid_domain(self, domain: str) -> bool:
        """Validate a domain against TLD list and exclude file-like patterns.
        
        Args:
            domain: Domain string to validate.
            
        Returns:
            True if domain is valid, False otherwise.
        """
        if not domain or "." not in domain:
            return False
        
        # Check for file extensions
        domain_lower = domain.lower()
        for ext in self.FILE_EXTENSIONS:
            if domain_lower.endswith(ext):
                return False
        
        # Extract TLD
        parts = domain.rsplit(".", 1)
        if len(parts) != 2:
            return False
        
        tld = parts[1].lower()
        return tld in self.VALID_TLDS
    
    def _is_private_ip(self, ip: str) -> bool:
        """Check if an IP address is private/internal.
        
        Args:
            ip: IP address string.
            
        Returns:
            True if IP is private, False otherwise.
        """
        try:
            octets = [int(o) for o in ip.split(".")]
            if len(octets) != 4:
                return False
            
            # 10.0.0.0/8
            if octets[0] == 10:
                return True
            
            # 172.16.0.0/12
            if octets[0] == 172 and 16 <= octets[1] <= 31:
                return True
            
            # 192.168.0.0/16
            if octets[0] == 192 and octets[1] == 168:
                return True
            
            # 127.0.0.0/8 (loopback)
            if octets[0] == 127:
                return True
            
            return False
        except (ValueError, IndexError):
            return False
