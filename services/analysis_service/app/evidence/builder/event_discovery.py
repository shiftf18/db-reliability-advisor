"""
Event Discovery for DBADV-02.

Discovers meaningful context events from logs.
"""

from __future__ import annotations

from ...contracts.models import AnalysisRequest
from ..normalizer import NormalizedLogObservation


def discover_context_events(
    logs: list[NormalizedLogObservation], request: AnalysisRequest
) -> list[NormalizedLogObservation]:
    """
    Discover meaningful context events from logs.

    Looks for:
    - Deployment events
    - Service restarts
    - Scenario markers
    - Alert triggers

    Args:
        logs: List of normalized log observations
        request: Analysis request with target service

    Returns:
        List of context event logs
    """
    context_events = []
    for log in logs:
        if not isinstance(log.value, dict):
            continue

        event_type = log.value.get("event")
        if event_type in ("deployment", "restart", "scenario_marker", "alert_trigger"):
            # Verify it's for our target service
            service = log.value.get("service")
            if service == request.target or service is None:
                context_events.append(log)

    return context_events
