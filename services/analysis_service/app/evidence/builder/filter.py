"""
Filter for DBADV-02.

Filters out irrelevant evidence records.
"""

from __future__ import annotations

from ...contracts.models import AnalysisRequest
from ..normalizer import NormalizedLogObservation, NormalizedMetric, NormalizedMongoMetadata


def filter_evidence[T: NormalizedMetric | NormalizedLogObservation | NormalizedMongoMetadata](
    evidence: list[T], request: AnalysisRequest
) -> list[T]:
    """
    Filter out irrelevant evidence records.

    Args:
        evidence: List of normalized evidence items
        request: Analysis request with target service

    Returns:
        Filtered list of evidence
    """
    if not evidence:
        return evidence

    # Check the type of the first item to determine filter strategy
    first = evidence[0]

    if isinstance(first, NormalizedMetric):
        return _filter_metrics(evidence, request)
    elif isinstance(first, NormalizedLogObservation):
        return evidence
    elif isinstance(first, NormalizedMongoMetadata):
        return _filter_metadata(evidence, request)

    return evidence


def _filter_metrics(
    metrics: list[NormalizedMetric], request: AnalysisRequest
) -> list[NormalizedMetric]:
    """Filter out irrelevant metrics."""
    # Prometheus and Loki adapter filters already.
    # Other metric sources (if any) would need filtering here.
    return metrics


def _filter_metadata(
    metadata: list[NormalizedMongoMetadata], request: AnalysisRequest
) -> list[NormalizedMongoMetadata]:
    """Filter out irrelevant metadata."""
    return metadata
