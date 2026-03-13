
import pytest
from validator import validate_response

LONG_GOOD = "A" * 150


def test_valid_plain_response():
    result = validate_response("architect", "Design a system", LONG_GOOD)
    assert result["valid"] is True
    assert result["errors"] == []


def test_empty_response():
    result = validate_response("architect", "task", "")
    assert result["valid"] is False
    assert any("empty" in e.lower() for e in result["errors"])


def test_too_short_response():
    result = validate_response("architect", "task", "Short answer.")
    assert result["valid"] is False
    assert any("short" in e.lower() for e in result["errors"])


def test_valid_json_agent_good_json():
    payload = '{"steps": ["step1", "step2"], "agents": ["a", "b"]}' + " " * 60
    result = validate_response("planner", "plan something", payload)
    assert result["valid"] is True


def test_valid_json_agent_bad_json():
    bad_json = "{steps: [step1, step2]}" + " " * 80
    result = validate_response("planner", "plan something", bad_json)
    assert result["valid"] is False
    assert any("JSON" in e for e in result["errors"])


def test_valid_json_agent_scalar_json():
    scalar = '"just a string"' + " " * 90
    result = validate_response("router", "route this", scalar)
    assert result["valid"] is False
    assert any("object or array" in e for e in result["errors"])


def test_mismatched_write_file_tags():
    response = "<write_file path='a.py'>code