"""
tests/test_context_manager.py

Unit tests for agent.context_manager:
  - FindingsContext deduplication, confidence upgrades, pruning, and rendering
  - ContextManager injection placement and stale-injection replacement
"""

import pytest

from agent.context_manager import ContextManager, FindingsContext, truncate_tool_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ip(value: str, confidence: float = 1.0, target: str = "10.10.10.0/24") -> dict:
    return {"finding_type": "ip", "value": value, "target": target, "confidence": confidence}


def _domain(value: str, confidence: float = 1.0, target: str = "example.com") -> dict:
    return {"finding_type": "domain", "value": value, "target": target, "confidence": confidence}


def _make_messages(*roles: str) -> list[dict]:
    """Build a minimal message list from a sequence of role strings."""
    role_content = {
        "system": "You are a pentest agent.",
        "user": "Run nmap.",
        "assistant": "Running nmap now.",
    }
    return [{"role": r, "content": role_content.get(r, r)} for r in roles]


# ---------------------------------------------------------------------------
# FindingsContext — deduplication
# ---------------------------------------------------------------------------

class TestFindingsDedup:
    def test_same_finding_twice_stores_once(self):
        fc = FindingsContext()
        finding = _ip("10.0.0.1", confidence=0.7)
        fc.update([finding])
        fc.update([finding])

        bucket = fc._findings["ip"]
        assert len(bucket) == 1, "Duplicate finding should not be stored twice"

    def test_version_increments_only_once_for_no_op_update(self):
        fc = FindingsContext()
        finding = _ip("10.0.0.1", confidence=0.7)
        fc.update([finding])
        v_after_first = fc.version

        fc.update([finding])          # exact duplicate — no change
        assert fc.version == v_after_first, "No-op update must not bump _version"

    def test_different_values_stored_separately(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1"), _ip("10.0.0.2")])
        assert len(fc._findings["ip"]) == 2

    def test_same_value_different_target_stored_separately(self):
        """(value, target) is the dedup key, not value alone."""
        fc = FindingsContext()
        fc.update([
            _ip("10.0.0.1", target="net-a"),
            _ip("10.0.0.1", target="net-b"),
        ])
        assert len(fc._findings["ip"]) == 2


# ---------------------------------------------------------------------------
# FindingsContext — confidence upgrade
# ---------------------------------------------------------------------------

class TestConfidenceUpgrade:
    def test_higher_confidence_replaces_lower(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1", confidence=0.5)])
        fc.update([_ip("10.0.0.1", confidence=0.9)])

        bucket = fc._findings["ip"]
        assert len(bucket) == 1
        assert bucket[0]["confidence"] == pytest.approx(0.9)

    def test_lower_confidence_does_not_replace_higher(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1", confidence=0.9)])
        fc.update([_ip("10.0.0.1", confidence=0.3)])

        assert fc._findings["ip"][0]["confidence"] == pytest.approx(0.9)

    def test_equal_confidence_does_not_change_version(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1", confidence=0.7)])
        v = fc.version
        fc.update([_ip("10.0.0.1", confidence=0.7)])
        assert fc.version == v

    def test_upgrade_bumps_version(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1", confidence=0.5)])
        v = fc.version
        fc.update([_ip("10.0.0.1", confidence=0.9)])
        assert fc.version == v + 1


# ---------------------------------------------------------------------------
# FindingsContext — pruning
# ---------------------------------------------------------------------------

class TestFindingsPruning:
    def test_max_items_enforced(self):
        fc = FindingsContext(max_items_per_type=20)
        findings = [_ip(f"10.0.0.{i}", confidence=i / 100) for i in range(30)]
        fc.update(findings)

        assert len(fc._findings["ip"]) == 20

    def test_highest_confidence_retained_after_prune(self):
        fc = FindingsContext(max_items_per_type=20)
        # confidences 0.00 … 0.29; top-20 are indices 10..29 → conf 0.10..0.29
        findings = [_ip(f"10.0.0.{i}", confidence=i / 100) for i in range(30)]
        fc.update(findings)

        retained_confidences = sorted(e["confidence"] for e in fc._findings["ip"])
        # The 20 highest confidence values are i/100 for i in 10..29
        expected = sorted(i / 100 for i in range(10, 30))
        assert retained_confidences == pytest.approx(expected)

    def test_low_confidence_entries_dropped(self):
        fc = FindingsContext(max_items_per_type=20)
        findings = [_ip(f"10.0.0.{i}", confidence=i / 100) for i in range(30)]
        fc.update(findings)

        retained_values = {e["value"] for e in fc._findings["ip"]}
        # i=0..9 should have been pruned
        for i in range(10):
            assert f"10.0.0.{i}" not in retained_values

    def test_custom_max_items_respected(self):
        fc = FindingsContext(max_items_per_type=5)
        fc.update([_ip(f"192.168.1.{i}") for i in range(10)])
        assert len(fc._findings["ip"]) == 5


# ---------------------------------------------------------------------------
# FindingsContext — render
# ---------------------------------------------------------------------------

class TestRender:
    def test_render_empty(self):
        fc = FindingsContext()
        assert fc.render() == "No findings collected yet."

    def test_render_empty_after_clearing_bucket(self):
        """Edge case: bucket exists but is empty list."""
        fc = FindingsContext()
        fc._findings["ip"]  # touch key, creates empty list
        assert fc.render() == "No findings collected yet."

    def test_render_contains_type_counts(self):
        fc = FindingsContext()
        fc.update([_ip(f"10.0.0.{i}") for i in range(3)])
        fc.update([_domain(f"sub{i}.example.com") for i in range(7)])

        rendered = fc.render()
        assert "ip (3)" in rendered
        assert "domain (7)" in rendered

    def test_render_version_header(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1")])
        assert f"[Findings v{fc.version}]" in fc.render()

    def test_render_shows_max_5_values(self):
        fc = FindingsContext()
        fc.update([_ip(f"10.0.0.{i}") for i in range(10)])
        rendered = fc.render()
        # Only 5 shown inline, rest in suffix
        assert "(+5 more)" in rendered

    def test_render_no_overflow_suffix_when_lte_5(self):
        fc = FindingsContext()
        fc.update([_ip(f"10.0.0.{i}") for i in range(5)])
        rendered = fc.render()
        assert "more)" not in rendered

    def test_version_increments_on_new_finding(self):
        fc = FindingsContext()
        v0 = fc.version
        fc.update([_ip("10.0.0.1")])
        assert fc.version == v0 + 1

    def test_version_does_not_increment_on_no_op(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1")])
        v1 = fc.version
        fc.update([_ip("10.0.0.1")])
        assert fc.version == v1


# ---------------------------------------------------------------------------
# FindingsContext — get_all_values
# ---------------------------------------------------------------------------

class TestGetAllValues:
    def test_returns_flat_set(self):
        fc = FindingsContext()
        fc.update([_ip("10.0.0.1"), _domain("evil.example.com")])
        assert fc.get_all_values() == {"10.0.0.1", "evil.example.com"}

    def test_empty_returns_empty_set(self):
        fc = FindingsContext()
        assert fc.get_all_values() == set()


# ---------------------------------------------------------------------------
# ContextManager — injection placement
# ---------------------------------------------------------------------------

class TestPrepareMessagesInjectionPlacement:
    def test_injection_before_last_user_message(self):
        """
        messages = [system, user, assistant, user]
        Injection must land at index 3 (immediately before the 4th element,
        which was the last user message).
        """
        ctx = ContextManager()
        messages = _make_messages("system", "user", "assistant", "user")
        result = ctx.prepare_messages(messages, "sys")

        # Original 4 msgs + 1 injection = 5 total
        assert len(result) == 5

        # Injection is at index 3
        injection = result[3]
        assert injection["role"] == "system"
        assert "CURRENT STATE:" in injection["content"]
        assert injection.get("_meta", {}).get("findings_injection") is True

        # Last element is still the user message
        assert result[4]["role"] == "user"

    def test_injection_content_contains_findings(self):
        ctx = ContextManager()
        ctx.findings_ctx.update([_ip("172.16.0.1")])
        messages = _make_messages("user")
        result = ctx.prepare_messages(messages, "sys")

        injection = next(m for m in result if m.get("_meta", {}).get("findings_injection"))
        assert "172.16.0.1" in injection["content"]

    def test_no_user_message_appends_at_end(self):
        """Graceful fallback: if no user message exists, append injection last."""
        ctx = ContextManager()
        messages = _make_messages("system", "assistant")
        result = ctx.prepare_messages(messages, "sys")

        assert result[-1].get("_meta", {}).get("findings_injection") is True

    def test_input_messages_not_mutated(self):
        ctx = ContextManager()
        original = _make_messages("system", "user")
        original_copy = [m.copy() for m in original]
        ctx.prepare_messages(original, "sys")

        # Original list length unchanged
        assert len(original) == len(original_copy)
        for orig, copy_ in zip(original, original_copy):
            assert orig == copy_

    def test_only_user_message_gets_injection_before_it(self):
        ctx = ContextManager()
        messages = _make_messages("user")
        result = ctx.prepare_messages(messages, "sys")

        assert len(result) == 2
        assert result[0].get("_meta", {}).get("findings_injection") is True
        assert result[1]["role"] == "user"


# ---------------------------------------------------------------------------
# ContextManager — stale injection replacement
# ---------------------------------------------------------------------------

class TestPrepareMessagesReplacesOldInjection:
    def test_single_injection_after_two_calls(self):
        """Calling prepare_messages twice must not accumulate injection messages."""
        ctx = ContextManager()
        messages = _make_messages("system", "user", "assistant", "user")

        ctx.findings_ctx.update([_ip("10.0.0.1")])
        first_pass = ctx.prepare_messages(messages, "sys")

        ctx.findings_ctx.update([_ip("10.0.0.2")])
        second_pass = ctx.prepare_messages(first_pass, "sys")

        injections = [
            m for m in second_pass
            if m.get("_meta", {}).get("findings_injection")
        ]
        assert len(injections) == 1, (
            f"Expected exactly 1 injection, found {len(injections)}"
        )

    def test_second_injection_reflects_latest_findings(self):
        ctx = ContextManager()
        messages = _make_messages("user")

        ctx.findings_ctx.update([_ip("10.0.0.1")])
        pass1 = ctx.prepare_messages(messages, "sys")

        ctx.findings_ctx.update([_ip("192.168.99.1")])
        pass2 = ctx.prepare_messages(pass1, "sys")

        injection = next(m for m in pass2 if m.get("_meta", {}).get("findings_injection"))
        assert "192.168.99.1" in injection["content"]
        # Old value should still be there (it was added, not replaced in findings)
        assert "10.0.0.1" in injection["content"]

    def test_multiple_stale_injections_all_removed(self):
        """Edge case: if somehow two injections sneak in, both are stripped."""
        ctx = ContextManager()
        stale = {
            "role": "system",
            "content": "CURRENT STATE:\nold",
            "_meta": {"findings_injection": True},
        }
        messages = [stale, stale, {"role": "user", "content": "go"}]
        result = ctx.prepare_messages(messages, "sys")

        injections = [m for m in result if m.get("_meta", {}).get("findings_injection")]
        assert len(injections) == 1


# ---------------------------------------------------------------------------
# truncate_tool_output
# ---------------------------------------------------------------------------

# Shared fixture: 100 lines each 20 chars wide → 2000 chars total (plus newlines)
def _multiline(n_lines: int = 100, line_len: int = 19) -> str:
    """Build an output with *n_lines* lines of length *line_len* + newline."""
    return "\n".join(f"{'x' * line_len}" for _ in range(n_lines))


class TestTruncateToolOutput:

    # ------------------------------------------------------------------
    # Pass-through
    # ------------------------------------------------------------------

    def test_short_output_returned_unchanged(self):
        output = "hello world\nline 2"
        assert truncate_tool_output(output, max_chars=4000) is output  # same object

    def test_exactly_max_chars_returned_unchanged(self):
        output = "a" * 4000
        result = truncate_tool_output(output, max_chars=4000)
        assert result == output

    # ------------------------------------------------------------------
    # Single-line fallback
    # ------------------------------------------------------------------

    def test_single_line_uses_hard_truncation(self):
        output = "A" * 8000          # no newlines
        result = truncate_tool_output(output, max_chars=4000)
        assert result == "A" * 4000 + "...[truncated]"

    def test_single_line_no_bridge_message(self):
        output = "X" * 5000
        result = truncate_tool_output(output, max_chars=4000)
        assert "omitted" not in result

    def test_single_line_length_is_max_chars_plus_suffix(self):
        output = "B" * 5000
        result = truncate_tool_output(output, max_chars=4000)
        assert len(result) == len("B" * 4000 + "...[truncated]")

    # ------------------------------------------------------------------
    # Multi-line head/tail strategy
    # ------------------------------------------------------------------

    def test_result_shorter_than_input(self):
        output = _multiline(300)       # 5999 chars — well above 4000
        result = truncate_tool_output(output, max_chars=4000)
        assert len(result) < len(output)

    def test_bridge_message_present(self):
        output = _multiline(300)   # 5999 chars — truncation fires
        result = truncate_tool_output(output, max_chars=4000)
        assert "chars omitted" in result
        assert "findings auto-extracted to database" in result

    def test_head_is_present_in_result(self):
        # First line of multi-line output must appear in result
        output = _multiline(200)
        first_line = output.split("\n")[0]
        result = truncate_tool_output(output, max_chars=4000)
        assert first_line in result

    def test_tail_is_present_in_result(self):
        # Last line of multi-line output must appear in result
        output = _multiline(200)
        last_line = output.split("\n")[-1]
        result = truncate_tool_output(output, max_chars=4000)
        assert last_line in result

    def test_head_does_not_split_mid_line(self):
        """Head boundary must land on a complete line — no partial lines."""
        lines = [f"line_{i:04d}" for i in range(500)]
        output = "\n".join(lines)
        result = truncate_tool_output(output, max_chars=4000)

        head_part = result.split("[...")[0]    # everything before the bridge
        # Strip trailing whitespace/newlines then check last token is a full line token
        last_head_line = head_part.rstrip("\n").split("\n")[-1]
        assert last_head_line.startswith("line_"), (
            f"Head ended mid-token: {last_head_line!r}"
        )

    def test_tail_does_not_split_mid_line(self):
        """Tail boundary must start on a complete line — no partial lines."""
        lines = [f"line_{i:04d}" for i in range(500)]
        output = "\n".join(lines)
        result = truncate_tool_output(output, max_chars=4000)

        tail_part = result.split("...]\n\n")[-1]   # everything after the bridge
        first_tail_line = tail_part.lstrip("\n").split("\n")[0]
        assert first_tail_line.startswith("line_"), (
            f"Tail started mid-token: {first_tail_line!r}"
        )

    def test_omitted_count_is_accurate(self):
        """The omitted count in the bridge must equal len(input) - len(head) - len(tail).

        We verify this by reconstructing head and tail from the result string and
        using the same formula the implementation uses: omitted = len(input) - len(head) - len(tail).
        The bridge itself is NOT included in that equation.
        """
        import re
        lines = [f"line_{i:04d}" for i in range(500)]  # 4999 chars
        output = "\n".join(lines)
        result = truncate_tool_output(output, max_chars=4000)

        m = re.search(r"\[\.\.\.(\d+) chars omitted", result)
        assert m, "Bridge message not found in result"
        reported_omitted = int(m.group(1))

        # Split result into head / bridge / tail at the bridge markers
        bridge_open  = "\n\n[..."
        bridge_close = "...]\n\n"
        open_idx  = result.index(bridge_open)
        close_idx = result.index(bridge_close) + len(bridge_close)

        head = result[:open_idx]
        tail = result[close_idx:]
        actual_omitted = len(output) - len(head) - len(tail)

        assert reported_omitted == actual_omitted, (
            f"Bridge reports {reported_omitted} omitted but actual omission is {actual_omitted}"
        )

    def test_custom_max_chars_respected(self):
        output = _multiline(100)   # ~2000 chars
        result = truncate_tool_output(output, max_chars=500)
        # Result is meaningfully shorter than input
        assert len(result) < len(output) // 2

    def test_multiline_output_no_truncated_suffix(self):
        """Multi-line path must NOT append '...[truncated]'."""
        output = _multiline(200)
        result = truncate_tool_output(output, max_chars=4000)
        assert "...[truncated]" not in result
