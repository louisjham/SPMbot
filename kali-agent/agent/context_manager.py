"""
context_manager.py - Findings-aware context injection for the Kali agent loop.

FindingsContext accumulates structured recon findings (IPs, ports, domains, etc.)
across tool calls and renders them as a compact summary string.

ContextManager wraps FindingsContext and splices a system injection message
carrying the current findings state directly before the last user message,
keeping the LLM grounded in live enumeration data without polluting history.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# FindingsContext
# ---------------------------------------------------------------------------

@dataclass
class FindingsContext:
    """
    Accumulates and deduplicates pentesting findings across agent iterations.

    Each finding is a dict with at least:
        finding_type: str   e.g. "ip", "open_port", "domain"
        value:        str   the discovered value
        target:       str   the scanned target (scope anchor)
        confidence:   float 0.0-1.0 (optional, defaults to 1.0)
    """

    max_items_per_type: int = 20

    # Private fields — not exposed as constructor params.
    _findings: defaultdict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list), repr=False
    )
    _version: int = field(default=0, repr=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, new_findings: list[dict[str, Any]]) -> None:
        """
        Merge *new_findings* into the internal store.

        Deduplication key: (finding_type, value, target).
        On collision the entry with the higher confidence is kept.
        Each type bucket is then pruned to *max_items_per_type* by confidence
        (highest first).  _version is incremented on any net change.
        """
        changed = False

        for raw in new_findings:
            ftype: str = raw.get("finding_type", "unknown")
            value: str = str(raw.get("value", ""))
            target: str = str(raw.get("target", ""))
            confidence: float = float(raw.get("confidence", 1.0))

            bucket: list[dict[str, Any]] = self._findings[ftype]

            # Find existing entry with same dedup key
            existing_idx: int | None = None
            for idx, entry in enumerate(bucket):
                if entry["value"] == value and entry["target"] == target:
                    existing_idx = idx
                    break

            if existing_idx is not None:
                if confidence > bucket[existing_idx]["confidence"]:
                    bucket[existing_idx] = {
                        "finding_type": ftype,
                        "value": value,
                        "target": target,
                        "confidence": confidence,
                    }
                    changed = True
                # else: duplicate with equal/lower confidence — skip
            else:
                bucket.append({
                    "finding_type": ftype,
                    "value": value,
                    "target": target,
                    "confidence": confidence,
                })
                changed = True

        # Prune each bucket to max_items_per_type (highest confidence wins)
        for ftype, bucket in self._findings.items():
            if len(bucket) > self.max_items_per_type:
                pruned = sorted(bucket, key=lambda e: e["confidence"], reverse=True)[
                    : self.max_items_per_type
                ]
                if pruned != bucket:
                    self._findings[ftype] = pruned
                    changed = True

        if changed:
            self._version += 1

    def render(self) -> str:
        """
        Return a compact human-readable summary of all findings.

        Example output:
            [Findings v3]
              ip (3): 10.10.14.3, 192.168.1.1, 10.0.0.5
              open_port (5): 22/tcp, 80/tcp, 443/tcp (+2 more)
              domain (12): sub1.example.com, sub2.example.com (+10 more)
        """
        _MAX_SHOW = 5

        if not self._findings or all(len(v) == 0 for v in self._findings.values()):
            return "No findings collected yet."

        lines: list[str] = [f"[Findings v{self._version}]"]

        for ftype in sorted(self._findings.keys()):
            bucket = self._findings[ftype]
            if not bucket:
                continue

            total = len(bucket)
            # Sort by confidence desc for display
            sorted_bucket = sorted(bucket, key=lambda e: e["confidence"], reverse=True)
            shown = sorted_bucket[:_MAX_SHOW]
            values_str = ", ".join(e["value"] for e in shown)

            if total > _MAX_SHOW:
                values_str += f" (+{total - _MAX_SHOW} more)"

            lines.append(f"  {ftype} ({total}): {values_str}")

        return "\n".join(lines)

    def get_all_values(self) -> set[str]:
        """Return a flat set of every finding value across all types."""
        return {
            entry["value"]
            for bucket in self._findings.values()
            for entry in bucket
        }

    # ------------------------------------------------------------------
    # Convenience read-only properties
    # ------------------------------------------------------------------

    @property
    def version(self) -> int:
        return self._version

    @property
    def is_empty(self) -> bool:
        return not self._findings or all(
            len(v) == 0 for v in self._findings.values()
        )


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------

class ContextManager:
    """
    Injects a live findings summary into outgoing message lists.

    Usage inside the agent loop::

        ctx_mgr = ContextManager()
        ctx_mgr.findings_ctx.update(tool_findings)
        messages = ctx_mgr.prepare_messages(messages, system_prompt)
        response = llm.complete(messages)
    """

    _INJECTION_META_KEY = "findings_injection"

    def __init__(self, max_context_tokens: int = 8000) -> None:
        self.max_context_tokens = max_context_tokens
        self.findings_ctx = FindingsContext()

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,  # noqa: ARG002 — reserved for future token trimming
    ) -> list[dict[str, Any]]:
        """
        Return a new message list with a findings injection injected before
        the last user message.

        Steps:
        1. Strip any previous findings injections (identified by _meta flag).
        2. Build a fresh injection message with the current findings state.
        3. Insert it immediately before the last message whose role=="user".
        4. Return the new list; the original *messages* is never mutated.
        """
        # Deep-copy so we never mutate the caller's list
        result: list[dict[str, Any]] = copy.deepcopy(messages)

        # 1. Remove stale injections
        result = [
            msg for msg in result
            if not (
                isinstance(msg.get("_meta"), dict)
                and msg["_meta"].get(self._INJECTION_META_KEY)
            )
        ]

        # 2. Build the injection message
        injection: dict[str, Any] = {
            "role": "system",
            "content": f"CURRENT STATE:\n{self.findings_ctx.render()}",
            "_meta": {self._INJECTION_META_KEY: True},
        }

        # 3. Find insertion point — last user message
        last_user_idx: int | None = None
        for idx in range(len(result) - 1, -1, -1):
            if result[idx].get("role") == "user":
                last_user_idx = idx
                break

        if last_user_idx is not None:
            result.insert(last_user_idx, injection)
        else:
            # No user message found — append at end as fallback
            result.append(injection)

        return result


# ---------------------------------------------------------------------------
# truncate_tool_output
# ---------------------------------------------------------------------------

def truncate_tool_output(output: str, max_chars: int = 4000) -> str:
    """
    Trim long tool output to *max_chars* while preserving context at both ends.

    Strategy (multi-line output):
        head  = first 60 % of budget, snapped back to the nearest newline
        tail  = last  30 % of budget, snapped forward to the nearest newline
        bridge = "\n\n[...N chars omitted — findings auto-extracted to database...]\n\n"

    Edge case (no newlines in output):
        Return ``output[:max_chars] + "...[truncated]"`` — no head/tail split.

    If the output already fits in *max_chars* it is returned unchanged.
    """
    if len(output) <= max_chars:
        return output

    # Single-line fallback — don't split mid-line
    if "\n" not in output:
        return output[:max_chars] + "...[truncated]"

    head_target = int(max_chars * 0.6)
    tail_size   = int(max_chars * 0.3)

    # --- Head: snap backward to the last newline at-or-before head_target ---
    head_end = output.rfind("\n", 0, head_target + 1)
    if head_end == -1:
        # No newline found in the head window; keep up to the target as-is
        head_end = head_target
        head = output[:head_end]
    else:
        # Include the newline so head ends cleanly on a line boundary
        head = output[: head_end + 1]

    # --- Tail: snap forward to the first newline at-or-after tail_start_target ---
    tail_start_target = len(output) - tail_size
    tail_start = output.find("\n", tail_start_target)
    if tail_start == -1:
        # No newline found; start tail at the raw target position
        tail = output[tail_start_target:]
    else:
        # Skip the newline itself — the bridge already supplies blank lines
        tail = output[tail_start + 1 :]

    omitted = len(output) - len(head) - len(tail)
    bridge = (
        f"\n\n[...{omitted} chars omitted — findings auto-extracted to database...]\n\n"
    )
    return head + bridge + tail
