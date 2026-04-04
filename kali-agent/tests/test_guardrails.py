"""
Tests for FindingsGuardrail.

Tests the guardrail functionality that validates agent responses
against discovered findings to prevent hallucination.
"""

import pytest

from agent.context_manager import FindingsContext
from agent.guardrails import FindingsGuardrail


@pytest.fixture
def findings_context():
    """Create a FindingsContext with test findings."""
    ctx = FindingsContext()
    ctx.update([
        {"finding_type": "ip", "value": "10.10.14.3", "target": "test", "confidence": 1.0},
        {"finding_type": "ip", "value": "192.168.1.1", "target": "test", "confidence": 1.0},
    ])
    return ctx


@pytest.fixture
def guardrail(findings_context):
    """Create a FindingsGuardrail with test findings context."""
    return FindingsGuardrail(findings_context)


def test_clean_response(guardrail):
    """Test response with only known findings produces no warnings."""
    response = "Nmap found port 22 open on 10.10.14.3"
    warnings = guardrail.check_response(response)

    assert warnings == []


def test_hallucinated_ip(guardrail):
    """Test response with unknown IP produces warning."""
    response = "We should scan 172.16.0.99 next"
    warnings = guardrail.check_response(response)

    assert len(warnings) == 1
    assert warnings[0]["value"] == "172.16.0.99"
    assert warnings[0]["pattern_type"] == "ipv4"


def test_whitelisted_ip(guardrail):
    """Test whitelisted IPs produce no warnings."""
    response = "Binding to 127.0.0.1"
    warnings = guardrail.check_response(response)

    assert warnings == []


def test_code_block_ignored(guardrail):
    """Test IPs in code blocks are ignored."""
    response = """Here's the output:
```
10.99.99.99 is up
```
Done."""
    warnings = guardrail.check_response(response)

    assert warnings == []


def test_multiple_warnings(guardrail):
    """Test multiple unverified references produce multiple warnings."""
    response = "Found 10.10.14.3 and 10.99.1.1 and CVE-2024-9999"
    warnings = guardrail.check_response(response)

    assert len(warnings) == 2

    # Extract values from warnings
    warning_values = {w["value"] for w in warnings}
    assert "10.99.1.1" in warning_values
    assert "CVE-2024-9999" in warning_values

    # Check pattern types
    for w in warnings:
        if w["value"] == "10.99.1.1":
            assert w["pattern_type"] == "ipv4"
        elif w["value"] == "CVE-2024-9999":
            assert w["pattern_type"] == "cve"


def test_annotate_adds_warning_text(guardrail):
    """Test annotate() adds warning text for unverified references."""
    response = "We found 10.10.14.3 but need to check 172.16.0.99"
    annotated_text, warnings = guardrail.annotate(response)

    # Check that warnings were generated
    assert len(warnings) == 1
    assert warnings[0]["value"] == "172.16.0.99"

    # Check that warning text was added
    assert "⚠️ Unverified references" in annotated_text
    assert "172.16.0.99" in annotated_text
    assert "Cross-check before acting" in annotated_text


def test_annotate_no_warnings(guardrail):
    """Test annotate() returns unchanged text when no warnings."""
    response = "Nmap found port 22 open on 10.10.14.3"
    annotated_text, warnings = guardrail.annotate(response)

    assert warnings == []
    assert annotated_text == response


def test_port_reference_warning(guardrail):
    """Test unverified port references produce warnings."""
    response = "We should check 443/tcp on the target"
    warnings = guardrail.check_response(response)

    assert len(warnings) == 1
    assert warnings[0]["value"] == "443/tcp"
    assert warnings[0]["pattern_type"] == "port"


def test_verified_port_no_warning(guardrail):
    """Test verified port references produce no warnings."""
    # Add a port finding
    guardrail.findings_context.update([
        {"finding_type": "open_port", "value": "443/tcp", "target": "test", "confidence": 1.0},
    ])

    response = "Nmap found 443/tcp open"
    warnings = guardrail.check_response(response)

    assert warnings == []


def test_multiple_code_blocks(guardrail):
    """Test multiple code blocks are all ignored."""
    response = """First block:
```
10.99.99.99
```
Text between
Second block:
```
172.16.0.1
```
End."""
    warnings = guardrail.check_response(response)

    assert warnings == []


def test_mixed_verified_and_unverified(guardrail):
    """Test mix of verified and unverified references."""
    response = "We have 10.10.14.3 but need to scan 172.16.0.99 and 192.168.1.1"
    warnings = guardrail.check_response(response)

    # Only the unverified IP should trigger a warning
    assert len(warnings) == 1
    assert warnings[0]["value"] == "172.16.0.99"
