import json
import re
from typing import Any

# Agents expected to return JSON in their primary response (selection, routing)
JSON_EXPECTED_AGENTS = {"selector", "router", "task_planner"}

# Patterns that indicate truncated output
TRUNCATION_PATTERNS = [
    r"\.\.\.\s*$",
    r"\[truncated\]",
    r"\[continued\]",
    r"etc\.\s*$",
    r"and so on\s*$",
]

MIN_RESPONSE_LENGTH = 100


def validate_response(agent_name: str, task: str, response: Any) -> dict:
    """
    Validate an agent's response for completeness and correctness.

    Args:
        agent_name: Name of the agent that produced the response
        task: The task description given to the agent
        response: The agent's response (str or dict)

    Returns:
        dict with keys: valid (bool), errors (list[str]), suggestions (str)
    """
    errors = []
    suggestions_parts = []

    response_str = response if isinstance(response, str) else json.dumps(response)

    # Check 1: Non-empty, minimum length
    # Bypass the length floor for valid JSON — a compact JSON object like
    # {"selected_agents": ["Architect"]} is complete even if under 100 chars.
    stripped = response_str.strip()
    _is_valid_json = False
    try:
        json.loads(stripped)
        _is_valid_json = True
    except (json.JSONDecodeError, ValueError):
        pass

    if not stripped:
        errors.append("Response is empty.")
        suggestions_parts.append("Ensure the agent returns a non-empty response.")
    elif not _is_valid_json and len(stripped) < MIN_RESPONSE_LENGTH:
        errors.append(
            f"Response too short: {len(stripped)} chars (minimum {MIN_RESPONSE_LENGTH})."
        )
        suggestions_parts.append(
            f"Response must be at least {MIN_RESPONSE_LENGTH} characters. "
            "Add more detail or explanation."
        )

    # Check 2: Valid JSON if expected
    agent_key = agent_name.lower().strip()
    if agent_key in JSON_EXPECTED_AGENTS:
        try:
            parsed = json.loads(stripped)
            if not isinstance(parsed, (dict, list)):
                errors.append("JSON response is not an object or array.")
                suggestions_parts.append("Return a JSON object or array, not a scalar.")
        except json.JSONDecodeError as e:
            errors.append(f"Expected valid JSON but got parse error: {e.msg} at pos {e.pos}.")
            suggestions_parts.append(
                "Wrap the response in valid JSON. Check for unquoted keys, "
                "trailing commas, or missing brackets."
            )

    # Check 3: Complete <write_file> tags
    open_tags = re.findall(r"<write_file\s+[^>]*>", response_str)
    close_tags = re.findall(r"</write_file>", response_str)

    if len(open_tags) != len(close_tags):
        errors.append(
            f"Mismatched <write_file> tags: {len(open_tags)} opening, "
            f"{len(close_tags)} closing."
        )
        suggestions_parts.append(
            "Every <write_file path=\"...\"> must have a matching </write_file> closing tag. "
            "Check for truncated file blocks."
        )

    # Check for write_file tags missing the path attribute
    for tag in open_tags:
        if 'path=' not in tag:
            errors.append(f"<write_file> tag missing required 'path' attribute: {tag!r}")
            suggestions_parts.append("Add path=\"filename\" to every <write_file> tag.")

    # Check 4: Truncation detection
    for pattern in TRUNCATION_PATTERNS:
        if re.search(pattern, stripped, re.IGNORECASE):
            errors.append(f"Response appears truncated (matched pattern: {pattern!r}).")
            suggestions_parts.append(
                "Complete the response fully. Do not use ellipsis or placeholder text "
                "to indicate continuation."
            )
            break

    valid = len(errors) == 0
    suggestions = " ".join(suggestions_parts) if suggestions_parts else "Response looks good."

    return {
        "valid": valid,
        "errors": errors,
        "suggestions": suggestions,
    }
