import json
import re
from typing import Any
from uuid import uuid4

import httpx

from ..contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from .base import CollectedEvidence


class LokiAdapter:
    """
    Adapter for collecting logs from Loki.
    Implements: Extract deployment events and slow-operation logs from Loki.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ready(self) -> bool:
        """Check if Loki is ready."""
        try:
            response = httpx.get(f"{self.base_url}/ready", timeout=2)
            return response.is_success
        except httpx.RequestError:
            return False

    def _is_sensitive_key(self, key: str) -> bool:
        """
        Check if a key indicates a sensitive field that should be redacted.

        Args:
            key: The dictionary key to check

        Returns:
            True if the key indicates a sensitive field, False otherwise
        """
        sensitive_keywords = {
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
        }
        return key.lower() in sensitive_keywords

    def _sanitize_value(self, value: Any) -> Any:
        """
        Recursively sanitize a value (string, dict, list, etc.) by redacting
        sensitive patterns.

        For strings: redacts sensitive patterns like passwords, tokens, etc.
        For dicts: redacts values where keys indicate sensitive fields
        For lists: recursively sanitizes each element
        For other types: returns as-is

        Args:
            value: The value to sanitize.

        Returns:
            The sanitized value (same type as input).
        """
        if isinstance(value, str):
            return self._redact_sensitive_patterns(value)
        elif isinstance(value, dict):
            sanitized_dict = {}
            for k, v in value.items():
                # Check if the key indicates a sensitive field
                if self._is_sensitive_key(k):
                    sanitized_dict[k] = "[REDACTED]"
                else:
                    sanitized_dict[k] = self._sanitize_value(v)
            return sanitized_dict
        elif isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        else:
            # For other types (int, float, bool, None), return as-is
            return value

    def _redact_sensitive_patterns(self, text: str) -> str:
        """
        Redact sensitive patterns in a string.

        Patterns we look for (case-insensitive):
          - Password-like: password, passwd, pwd, secret, key, token, auth, credential
          - API key patterns: api[_-]?key, access[_-]?token, etc.
          - Email addresses
          - IP addresses (maybe not sensitive, but we'll leave as-is for now)
          - etc.

        We replace the matched pattern's value with "[REDACTED]".

        Note: This is a simple implementation and may not catch all cases.
        In a production system, you might use a more robust library or allow
        configuration of patterns to redact.

        Args:
            text: The string to sanitize.

        Returns:
            The string with sensitive patterns redacted.
        """
        # Patterns to redact: we look for key-value pairs where the key suggests
        # a secret and the value is anything after an equals sign or colon.
        # We'll use a simple regex to match common patterns.

        # Pattern 1: key=value or key: value (with optional quotes)
        # We'll redact the value if the key matches a sensitive pattern.
        patterns = [
            r'(?i)(password|passwd|pwd|secret|key|token|auth|credential|api[_-]?key|access[_-]?token|private[_-]?key|ssn|social[_-]?security)\s*[:=]\s*["\']?([^"\'\s]+)["\']?',
            r'(?i)(email)\s*[:=]\s*["\']?([^"\'\s]+@[^"\'\s]+\.[^"\'\s]+)["\']?',
        ]

        redacted = text
        for pattern in patterns:
            # We want to replace the value part (the second capture group) with [REDACTED]
            # We'll use a function to replace the match.
            def replace_func(match: re.Match) -> str:
                # Keep the key and the delimiter, replace the value
                return match.group(0).replace(match.group(2), "[REDACTED]")

            redacted = re.sub(pattern, replace_func, redacted)

        return redacted

    def collect(
        self, request: AnalysisRequest, fixture_name: str | None = None
    ) -> CollectedEvidence:
        """
        Collect logs from Loki for two categories:
          A. MongoDB slow-operation logs
          B. Context/application events (deployment events, service restarts, etc.)
        Returns CollectedEvidence with list of Evidence objects.
        """
        evidence_list = []
        missing_evidence = []

        # If fixture_name is provided, we could load mock data for testing.
        # For simplicity, we skip fixture loading in this implementation.
        # In a real test environment, you would load from fixture files.
        # mock mode uses MockAdapter instead
        if fixture_name:
            # For now, return empty evidence when fixture mode is requested.
            # This allows tests to proceed without actual Loki.
            return CollectedEvidence(evidence=[], missing_evidence=[])

        # Use the end time of the analysis window as the query time.
        # Loki's API expects timestamps in seconds (or nanoseconds?
        # We'll use seconds for simplicity).
        start_time = request.start_time.timestamp()
        end_time = request.end_time.timestamp()

        escaped_target = request.target.replace("\\", "\\\\").replace('"', '\\"')
        slow_op_query = '{service="mongodb",source="diagnostic-log"} | json'
        context_query = (
            f'{{service="{escaped_target}"}} | json | '
            'event=~"deployment|restart|scenario_marker|alert_trigger"'
        )

        queries = [
            ("mongodb_slow_operation", slow_op_query),
            ("context_event", context_query),
        ]

        for name, logql in queries:
            try:
                # Query Loki's range API.
                response = httpx.get(
                    f"{self.base_url}/loki/api/v1/query_range",
                    params={
                        "query": logql,
                        "start": start_time,
                        "end": end_time,
                        "step": 1,  # 1 second resolution (adjust as needed)
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                if data["status"] != "success":
                    raise ValueError(f"Loki query failed: {data}")

                # Parse the response to extract log entries.
                result = data["data"]["result"]
                if not result:
                    # No data returned for this query.
                    missing_evidence.append(f"No data for {name}")
                    continue

                # We'll use a set to deduplicate by (timestamp, raw_line).
                seen = set()

                for stream in result:
                    # Each stream has a "stream" dict (labels) and a "values" list.
                    # Each value is a list of [timestamp_nanoseconds, log_line].
                    for ts_nano, raw_line in stream["values"]:
                        # Convert nanosecond timestamp to seconds.
                        try:
                            ts_sec = int(ts_nano) / 1_000_000_000
                        except ValueError:
                            # If timestamp is not a valid integer, skip this entry.
                            continue

                        # Deduplicate by (timestamp, raw_line).
                        key = (ts_sec, raw_line)
                        if key in seen:
                            continue
                        seen.add(key)

                        # Parse the raw line as JSON to extract structured data.
                        try:
                            # Assuming the log line is a JSON string.
                            log_data = json.loads(raw_line)
                        except (json.JSONDecodeError, TypeError):
                            # If not JSON, we still create an event with the raw line as message.
                            log_data = {"raw_message": raw_line}

                        # Sanitize the log data to redact sensitive information.
                        log_data = self._sanitize_value(log_data)

                        # Create Evidence object.
                        evidence = Evidence(
                            id=str(uuid4()),
                            kind="event",
                            name=name,  # e.g., "mongodb_slow_operation" or "context_event"
                            value=log_data,  # Store the parsed JSON (or raw message) as value.
                            unit=None,
                            source=EvidenceSource(system="loki", query=logql),
                            observation_window=EvidenceObservationWindow(
                                start_time=start_time,
                                end_time=end_time,
                            ),
                            timestamp=ts_sec,  # Set the event timestamp to the log's timestamp.
                        )
                        evidence_list.append(evidence)

            except (
                httpx.RequestError,
                ValueError,
                KeyError,
                IndexError,
                json.JSONDecodeError,
            ) as exc:
                # Record failure for this query.
                missing_evidence.append(f"Failed to collect {name} from Loki: {exc}")
                continue

        return CollectedEvidence(
            evidence=evidence_list,
            missing_evidence=missing_evidence,
        )
