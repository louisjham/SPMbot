"""
Tests for AgentStore findings operations.

Tests save_findings and get_findings with in-memory SQLite database.
"""

import asyncio
import os
import tempfile

import pytest

from store.sqlite import AgentStore


@pytest.fixture
async def store():
    """Create an in-memory SQLite store for testing."""
    # Use a temp file that get_findings can reconnect to
    # (get_findings opens its own connection, so pure :memory: won't work)
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    s = AgentStore(db_path)
    await s.initialize()
    yield s
    await s.close()
    # Cleanup
    for f in os.listdir(temp_dir):
        os.remove(os.path.join(temp_dir, f))
    os.rmdir(temp_dir)


class TestSaveFindings:
    """Tests for SQLiteStore.save_findings method."""

    @pytest.mark.asyncio
    async def test_insert_three_findings_different_types(self, store):
        """Insert 3 findings with different types and verify count."""
        findings = [
            {
                "task_id": "task-1",
                "conversation_id": "conv-1",
                "finding_type": "ip",
                "value": "192.168.1.1",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-1",
                "conversation_id": "conv-1",
                "finding_type": "domain",
                "value": "example.com",
                "source_skill": "web_recon",
            },
            {
                "task_id": "task-1",
                "conversation_id": "conv-1",
                "finding_type": "url",
                "value": "https://example.com/admin",
                "source_skill": "web_recon",
            },
        ]

        count = await store.save_findings(findings)
        assert count == 3

        # Verify all 3 are stored
        results = await store.get_findings("conv-1")
        assert len(results) == 3

        # Verify types are present
        types_found = {f["finding_type"] for f in results}
        assert types_found == {"ip", "domain", "url"}

    @pytest.mark.asyncio
    async def test_duplicate_updates_last_seen(self, store):
        """Insert duplicate finding and verify last_seen is updated, no new row."""
        finding = {
            "task_id": "task-2",
            "conversation_id": "conv-2",
            "finding_type": "ip",
            "value": "10.0.0.1",
            "target": "target-host",
            "source_skill": "nmap_scan",
        }

        # First insert
        await store.save_findings([finding])
        results = await store.get_findings("conv-2")
        assert len(results) == 1
        first_seen_original = results[0]["first_seen"]
        last_seen_original = results[0]["last_seen"]

        # Wait a tiny bit to ensure timestamp difference
        await asyncio.sleep(0.01)

        # Insert duplicate (same task_id, finding_type, value, target)
        await store.save_findings([finding])
        results = await store.get_findings("conv-2")

        # Should still be exactly 1 row
        assert len(results) == 1

        # first_seen should remain unchanged
        assert results[0]["first_seen"] == first_seen_original

        # last_seen should be updated
        assert results[0]["last_seen"] >= last_seen_original

    @pytest.mark.asyncio
    async def test_same_value_different_target_stores_both(self, store):
        """Insert same value but different target, verify both are stored."""
        findings = [
            {
                "task_id": "task-3",
                "conversation_id": "conv-3",
                "finding_type": "ip",
                "value": "172.16.0.1",
                "target": "target-A",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-3",
                "conversation_id": "conv-3",
                "finding_type": "ip",
                "value": "172.16.0.1",
                "target": "target-B",
                "source_skill": "nmap_scan",
            },
        ]

        count = await store.save_findings(findings)
        assert count == 2

        results = await store.get_findings("conv-3")
        assert len(results) == 2

        # Verify both targets are present
        targets = {f["target"] for f in results}
        assert targets == {"target-A", "target-B"}


class TestGetFindings:
    """Tests for SQLiteStore.get_findings method."""

    @pytest.mark.asyncio
    async def test_filter_by_conversation_id_isolation(self, store):
        """Insert 5 findings across 2 conversation_ids and verify isolation."""
        findings = [
            # 3 findings for conv-A
            {
                "task_id": "task-A1",
                "conversation_id": "conv-A",
                "finding_type": "ip",
                "value": "1.1.1.1",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-A2",
                "conversation_id": "conv-A",
                "finding_type": "domain",
                "value": "a.example.com",
                "source_skill": "web_recon",
            },
            {
                "task_id": "task-A3",
                "conversation_id": "conv-A",
                "finding_type": "url",
                "value": "https://a.example.com",
                "source_skill": "web_recon",
            },
            # 2 findings for conv-B
            {
                "task_id": "task-B1",
                "conversation_id": "conv-B",
                "finding_type": "ip",
                "value": "2.2.2.2",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-B2",
                "conversation_id": "conv-B",
                "finding_type": "email",
                "value": "admin@example.com",
                "source_skill": "web_recon",
            },
        ]

        await store.save_findings(findings)

        # Verify conv-A has 3 findings
        results_a = await store.get_findings("conv-A")
        assert len(results_a) == 3

        # Verify conv-B has 2 findings
        results_b = await store.get_findings("conv-B")
        assert len(results_b) == 2

        # Verify isolation - no cross-contamination
        values_a = {f["value"] for f in results_a}
        values_b = {f["value"] for f in results_b}
        assert values_a == {"1.1.1.1", "a.example.com", "https://a.example.com"}
        assert values_b == {"2.2.2.2", "admin@example.com"}

    @pytest.mark.asyncio
    async def test_filter_by_finding_type_ip(self, store):
        """Filter by finding_type='ip' and verify only IPs returned."""
        findings = [
            {
                "task_id": "task-4",
                "conversation_id": "conv-4",
                "finding_type": "ip",
                "value": "192.168.100.1",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-4",
                "conversation_id": "conv-4",
                "finding_type": "ip",
                "value": "192.168.100.2",
                "source_skill": "nmap_scan",
            },
            {
                "task_id": "task-4",
                "conversation_id": "conv-4",
                "finding_type": "domain",
                "value": "test.example.com",
                "source_skill": "web_recon",
            },
            {
                "task_id": "task-4",
                "conversation_id": "conv-4",
                "finding_type": "url",
                "value": "https://test.example.com/login",
                "source_skill": "web_recon",
            },
            {
                "task_id": "task-4",
                "conversation_id": "conv-4",
                "finding_type": "email",
                "value": "user@example.com",
                "source_skill": "web_recon",
            },
        ]

        await store.save_findings(findings)

        # Get only IPs
        results = await store.get_findings("conv-4", finding_type="ip")

        # Should only return 2 IP findings
        assert len(results) == 2

        # Verify all are type 'ip'
        for f in results:
            assert f["finding_type"] == "ip"

        # Verify correct values
        values = {f["value"] for f in results}
        assert values == {"192.168.100.1", "192.168.100.2"}
