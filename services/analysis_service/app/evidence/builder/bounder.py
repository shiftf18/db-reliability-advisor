"""
Bounder for DBADV-02.

Limits evidence size to prevent excessive growth.
"""

from __future__ import annotations

from ...contracts.models import Evidence


def bound_evidence(evidence_items: list[Evidence], max_items: int) -> list[Evidence]:
    """
    Limit evidence size to prevent excessive growth.

    Keeps the most important evidence types first based on priority.

    Args:
        evidence_items: List of evidence items
        max_items: Maximum number of evidence items to keep

    Returns:
        Bounded list of evidence items
    """
    if len(evidence_items) <= max_items:
        return evidence_items

    # Priority order for evidence kinds (lower = higher priority)
    priority_order = {
        "event": 0,
        "metric_comparison": 1,
        "query_comparison": 2,
        "query_plan": 3,
        "metadata": 4,
        "metric_window": 5,
        "query_window": 6,
    }

    # Sort by priority and take top N
    sorted_evidence = sorted(evidence_items, key=lambda e: priority_order.get(e.kind, 99))
    return sorted_evidence[:max_items]
