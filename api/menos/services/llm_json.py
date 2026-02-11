"""Shared utility for extracting JSON from LLM responses."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_json(response: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks.

    Args:
        response: Raw LLM response

    Returns:
        Parsed JSON dictionary, or empty dict if parsing fails
    """
    response = response.strip()
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    patterns = [
        r"```json\s*\n?(.*?)\n?```",
        r"```\s*\n?(.*?)\n?```",
        r"\{[\s\S]*\}",
    ]

    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL)
        if match:
            try:
                json_str = match.group(1) if "```" in pattern else match.group(0)
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                continue

    logger.warning("Failed to parse LLM response as JSON: %s", response[:200])
    return {}
