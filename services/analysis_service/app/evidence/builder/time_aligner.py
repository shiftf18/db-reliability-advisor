"""
Time Aligner for DBADV-02.

Aligns evidence to the requested analysis time window.
"""

from __future__ import annotations

from typing import Any

from ...contracts.models import AnalysisRequest
from ..normalizer import NormalizedLogObservation, NormalizedMetric, NormalizedMongoMetadata


def time_align_evidence[T: NormalizedMetric | NormalizedLogObservation | NormalizedMongoMetadata](
    evidence: list[T], request: AnalysisRequest
) -> list[T]:
    """
    Filter evidence to the requested time window.

    Args:
        evidence: List of normalized evidence items
        request: Analysis request with start_time and end_time

    Returns:
        Filtered list of evidence within the time window
    """
    aligned = []
    for item in evidence:
        if _is_within_window(item, request) or not _has_time_info(item):
            aligned.append(item)
    return aligned


def _has_time_info(item: Any) -> bool:
    """Check if item has any time information."""
    return any(
        [
            getattr(item, "timestamp", None) is not None,
            getattr(item, "start_time", None) is not None,
            getattr(item, "end_time", None) is not None,
        ]
    )


def _is_within_window(item: Any, request: AnalysisRequest) -> bool:
    """Check if item falls within the requested time window."""
    # Check timestamp
    if (
        hasattr(item, "timestamp")
        and item.timestamp
        and request.start_time <= item.timestamp <= request.end_time
    ):
        return True

    # Check observation window
    return (
        hasattr(item, "start_time")
        and hasattr(item, "end_time")
        and item.start_time
        and item.end_time
        and item.start_time >= request.start_time
        and item.end_time <= request.end_time
    )
