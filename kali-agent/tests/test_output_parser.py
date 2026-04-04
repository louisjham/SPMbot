"""
Tests for OutputParser - Tool-specific output parsing.

Tests each parser in OutputParser: nmap, gobuster, nuclei, and generic parsing.
"""

import pytest

from skills.output_parser import OutputParser, ParsedFinding


class TestParseNmap:
    """Tests for _parse_nmap method."""

    def test_parse_nmap_extracts_open_ports_and_target(self) -> None:
        """Parse nmap output with open ports and extract target IP."""
        parser = OutputParser()
        output = (
            "Nmap scan report for 10.10.14.3\n"
            "22/tcp open ssh\n"
            "80/tcp open http\n"
            "443/tcp open https\n"
        )
        
        findings = parser.parse(output, "nmap")
        
        assert len(findings) == 3
        
        # Verify all are open_port findings
        for finding in findings:
            assert finding.finding_type == "open_port"
            assert finding.target == "10.10.14.3"
            assert finding.confidence == 1.0
        
        # Verify services in context
        services = {f.value: f.context.get("service") for f in findings}
        assert services["22/tcp"] == "ssh"
        assert services["80/tcp"] == "http"
        assert services["443/tcp"] == "https"

    def test_parse_nmap_empty_returns_empty_list(self) -> None:
        """Parse nmap output with no open ports returns empty list."""
        parser = OutputParser()
        output = "Note: Host seems down."
        
        findings = parser.parse(output, "nmap")
        
        assert findings == []

    def test_parse_nmap_with_udp_ports(self) -> None:
        """Parse nmap output with UDP ports."""
        parser = OutputParser()
        output = "53/udp open domain\n123/udp open ntp\n"
        
        findings = parser.parse(output, "nmap")
        
        assert len(findings) == 2
        assert findings[0].value == "53/udp"
        assert findings[1].value == "123/udp"


class TestParseGobuster:
    """Tests for _parse_gobuster method."""

    def test_parse_gobuster_filters_404s(self) -> None:
        """Parse gobuster output and filter out 404 status codes."""
        parser = OutputParser()
        output = (
            "/admin (Status: 200)\n"
            "/login (Status: 301)\n"
            "/missing (Status: 404)\n"
        )
        
        findings = parser.parse(output, "gobuster", target="http://example.com")
        
        assert len(findings) == 2
        
        # Verify 404 is filtered out (values include target prefix when provided)
        values = [f.value for f in findings]
        assert "http://example.com/admin" in values
        assert "http://example.com/login" in values
        assert "/missing" not in values
        
        # Verify status codes in context
        status_codes = {f.value: f.context.get("status_code") for f in findings}
        assert status_codes["http://example.com/admin"] == 200
        assert status_codes["http://example.com/login"] == 301

    def test_parse_gobuster_without_target(self) -> None:
        """Parse gobuster output without target returns paths only."""
        parser = OutputParser()
        output = "/api (Status: 200)\n"
        
        findings = parser.parse(output, "gobuster", target=None)
        
        assert len(findings) == 1
        assert findings[0].value == "/api"


class TestParseNuclei:
    """Tests for _parse_nuclei method."""

    def test_parse_nuclei_extracts_vulnerability(self) -> None:
        """Parse nuclei output and extract vulnerability with severity."""
        parser = OutputParser()
        output = "[CVE-2021-44228] [critical] http://10.10.14.3:8080/api\n"
        
        findings = parser.parse(output, "nuclei")
        
        assert len(findings) == 1
        
        finding = findings[0]
        assert finding.finding_type == "vulnerability"
        assert finding.value == "CVE-2021-44228"
        assert finding.context.get("severity") == "critical"
        assert finding.context.get("matched") == "http://10.10.14.3:8080/api"
        assert finding.confidence == 1.0

    def test_parse_nuclei_multiple_vulnerabilities(self) -> None:
        """Parse nuclei output with multiple vulnerabilities."""
        parser = OutputParser()
        output = (
            "[xss-reflected] [medium] http://example.com/search?q=test\n"
            "[sqli-error] [high] http://example.com/users?id=1\n"
        )
        
        findings = parser.parse(output, "nuclei")
        
        assert len(findings) == 2
        assert findings[0].context.get("severity") == "medium"
        assert findings[1].context.get("severity") == "high"


class TestGenericParse:
    """Tests for _generic_parse method."""

    def test_generic_excludes_filenames(self) -> None:
        """Generic parser excludes file-like patterns from domain extraction."""
        parser = OutputParser()
        output = "Files: config.json setup.py app.example.com\n"
        
        findings = parser.parse(output, "unknown_tool")
        
        # Extract domain findings
        domains = [f.value for f in findings if f.finding_type == "domain"]
        
        # Verify filenames are NOT extracted
        assert "config.json" not in domains
        assert "setup.py" not in domains
        
        # Verify valid domain IS extracted
        assert "app.example.com" in domains

    def test_generic_ips_with_confidence(self) -> None:
        """Generic parser extracts IPs with confidence=0.7."""
        parser = OutputParser()
        output = "Connected to 192.168.1.1 via 10.0.0.1"
        
        findings = parser.parse(output, "unknown_tool")
        
        ip_findings = [f for f in findings if f.finding_type == "ip"]
        
        assert len(ip_findings) == 2
        
        # Verify confidence is 0.7 for generic extraction
        for finding in ip_findings:
            assert finding.confidence == 0.7
        
        # Verify both IPs extracted
        ips = {f.value for f in ip_findings}
        assert "192.168.1.1" in ips
        assert "10.0.0.1" in ips

    def test_generic_extracts_urls(self) -> None:
        """Generic parser extracts URLs."""
        parser = OutputParser()
        output = "Visit https://example.com/api or http://test.org/page\n"
        
        findings = parser.parse(output, "unknown_tool")
        
        url_findings = [f for f in findings if f.finding_type == "url"]
        
        assert len(url_findings) == 2
        urls = {f.value for f in url_findings}
        assert "https://example.com/api" in urls
        assert "http://test.org/page" in urls


class TestOutputParserEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_output_returns_empty_list(self) -> None:
        """Empty output returns empty list."""
        parser = OutputParser()
        
        assert parser.parse("", "nmap") == []
        assert parser.parse("", "gobuster") == []

    def test_none_output_returns_empty_list(self) -> None:
        """None output returns empty list."""
        parser = OutputParser()
        
        assert parser.parse("", "nmap") == []  # type: ignore

    def test_invalid_tool_name_uses_generic_parser(self) -> None:
        """Unknown tool name falls back to generic parser."""
        parser = OutputParser()
        output = "Server at 192.168.1.1 responded"
        
        findings = parser.parse(output, "unknown_tool")
        
        # Should use generic parser and extract IP
        assert len(findings) >= 1
        ip_findings = [f for f in findings if f.finding_type == "ip"]
        assert len(ip_findings) == 1
        assert ip_findings[0].confidence == 0.7
