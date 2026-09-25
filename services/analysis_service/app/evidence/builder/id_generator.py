"""
ID Generator for DBADV-02.

Assigns sequential evidence IDs (E1, E2, E3...).
"""

from __future__ import annotations

from ...contracts.models import Evidence


def assign_sequential_ids(evidence_items: list[Evidence]) -> list[Evidence]:
    """
    Assign sequential evidence IDs (E1, E2, E3...).

    Args:
        evidence_items: List of evidence items

    Returns:
        List with updated sequential IDs
    """
    for i, item in enumerate(evidence_items, 1):
        item.id = f"E{i}"
    return evidence_items
