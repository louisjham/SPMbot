"""
Tests for agent configuration.

Tests the temperature configuration and helper functions.
"""

import pytest

from agent.config import TEMPERATURE_MAP, get_temperature


def test_temperature_map_has_all_required_keys():
    """Test that TEMPERATURE_MAP contains all required keys."""
    required_keys = {
        "tool_call",
        "tool_params",
        "planning",
        "summarize",
        "structured_output",
        "default",
    }
    assert required_keys.issubset(TEMPERATURE_MAP.keys())


def test_temperature_values_in_valid_range():
    """Test that all temperature values are in valid range [0.0, 2.0]."""
    for phase, temp in TEMPERATURE_MAP.items():
        assert 0.0 <= temp <= 2.0, f"Temperature for {phase} is out of range: {temp}"


def test_get_temperature_for_known_phase():
    """Test get_temperature for known phases."""
    assert get_temperature("tool_call") == 0.1
    assert get_temperature("tool_params") == 0.0
    assert get_temperature("planning") == 0.7
    assert get_temperature("summarize") == 0.5
    assert get_temperature("structured_output") == 0.0
    assert get_temperature("default") == 0.4


def test_get_temperature_for_unknown_phase():
    """Test get_temperature returns default for unknown phase."""
    unknown_phase = "unknown_phase"
    result = get_temperature(unknown_phase)
    assert result == TEMPERATURE_MAP["default"]


def test_temperature_values_are_floats():
    """Test that all temperature values are floats."""
    for phase, temp in TEMPERATURE_MAP.items():
        assert isinstance(temp, float), f"Temperature for {phase} is not a float: {type(temp)}"


def test_tool_params_has_lowest_temperature():
    """Test that tool_params has the lowest temperature (most deterministic)."""
    assert TEMPERATURE_MAP["tool_params"] == 0.0
    assert TEMPERATURE_MAP["tool_params"] == min(TEMPERATURE_MAP.values())


def test_planning_has_highest_temperature():
    """Test that planning has the highest temperature (most creative)."""
    assert TEMPERATURE_MAP["planning"] == max(TEMPERATURE_MAP.values())
