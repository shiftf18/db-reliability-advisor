"""
Sanitizer for DBADV-02.

Sanitizes evidence values to remove PII/sensitive data.
"""

from __future__ import annotations

import re
from typing import Any

from ..normalizer import NormalizedLogObservation, NormalizedMetric, NormalizedMongoMetadata

# Sensitive key patterns
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "key",
    "token",
    "auth",
    "credential",
    "api_key",
    "access_token",
    "private_key",
    "ssn",
    "social_security",
    "email",
    "ip",
    "address",
    "host",
    "username",
}

# Regex patterns for sensitive data in strings
# Each pattern must have 2 capture groups: group 1 = key name, group 2 = value
SENSITIVE_PATTERNS = [
    r'(?i)(password|passwd|pwd|secret|key|token|auth|credential|api[_-]?key|access[_-]?token|private[_-]?key|ssn|social[_-]?security)\s*[:=]\s*["\']?([^"\'\s]+)["\']?',
    r'(?i)(email)\s*[:=]\s*["\']?([^"\'\s]+@[^"\'\s]+\.[^"\'\s]+)["\']?',
]


def sanitize_value(
    item: NormalizedMetric | NormalizedLogObservation | NormalizedMongoMetadata,
) -> NormalizedMetric | NormalizedLogObservation | NormalizedMongoMetadata:
    """
    Sanitize an evidence item's value.

    Args:
        item: Normalized evidence item

    Returns:
        Sanitized copy of the item
    """
    if isinstance(item, NormalizedMetric):
        # Metrics typically don't contain sensitive data
        return item

    elif isinstance(item, NormalizedLogObservation):
        if isinstance(item.value, dict):
            sanitized_value = _sanitize_dict(item.value)
            return item.model_copy(update={"value": sanitized_value})
        elif isinstance(item.value, str):
            sanitized_value = _sanitize_string(item.value)
            return item.model_copy(update={"value": sanitized_value})
        return item

    elif isinstance(item, NormalizedMongoMetadata):
        if isinstance(item.value, dict):
            sanitized_value = _sanitize_dict(item.value)
            return item.model_copy(update={"value": sanitized_value})
        elif isinstance(item.value, list):
            sanitized_value = [
                _sanitize_dict(v)
                if isinstance(v, dict)
                else _sanitize_string(v)
                if isinstance(v, str)
                else v
                for v in item.value
            ]
            return item.model_copy(update={"value": sanitized_value})
        return item

    return item


def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize a dictionary."""
    sanitized = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_dict(v)
                if isinstance(v, dict)
                else _sanitize_string(v)
                if isinstance(v, str)
                else v
                for v in value
            ]
        elif isinstance(value, str):
            sanitized[key] = _sanitize_string(value)
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_string(text: str) -> str:
    """Sanitize a string by redacting sensitive patterns."""
    redacted = text
    for pattern in SENSITIVE_PATTERNS:

        def replace_func(match: re.Match) -> str:
            return match.group(0).replace(match.group(2), "[REDACTED]")

        redacted = re.sub(pattern, replace_func, redacted)
    return redacted
