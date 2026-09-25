"""
Missing Evidence Tracker for DBADV-02.

Tracks missing evidence by comparing expected evidence with actual evidence.
"""

from __future__ import annotations

from ...contracts.models import AnalysisRequest, Evidence


def track_missing_evidence(
    evidence_items: list[Evidence],
    adapter_missing: list[str],
    request: AnalysisRequest,
    query_regression_evidence: set[str],
    connection_pressure_evidence: set[str],
) -> list[str]:
    """
    Track missing evidence by comparing expected evidence with actual evidence.

    Combines adapter-reported missing evidence with evidence that was expected
    but not found in the collected data.

    Args:
        evidence_items: List of built evidence items
        adapter_missing: Missing evidence reported by adapters
        request: Analysis request
        query_regression_evidence: Expected evidence for query regression scenario
        connection_pressure_evidence: Expected evidence for connection pressure scenario

    Returns:
        List of missing evidence descriptions
    """
    missing = list(adapter_missing)  # Start with adapter-reported missing

    # Get the set of evidence names we actually have
    found_names = {item.name for item in evidence_items}

    # Determine which scenario we're in based on available evidence
    if "request_p95_ms" in found_names and "documents_examined" in found_names:
        expected = query_regression_evidence
    elif "connection_utilization_percent" in found_names:
        expected = connection_pressure_evidence
    else:
        expected = set()

    # Find missing expected evidence
    for expected_name in expected:
        if expected_name not in found_names:
            missing.append(f"Expected evidence '{expected_name}' not found")

    # Add generic missing evidence if we have very little
    if len(evidence_items) < 3:
        missing.append("Insufficient evidence collected for meaningful analysis")

    return missing
