"""
Deduplicator for DBADV-02.

Removes duplicate evidence entries.
"""

from __future__ import annotations

from ..normalizer import NormalizedLogObservation, NormalizedMetric, NormalizedMongoMetadata


def deduplicate_evidence[T: NormalizedMetric | NormalizedLogObservation | NormalizedMongoMetadata](
    evidence: list[T],
) -> list[T]:
    """
    Remove duplicate evidence entries.

    Args:
        evidence: List of normalized evidence items

    Returns:
        Deduplicated list of evidence
    """
    if not evidence:
        return evidence

    # Check the type of the first item to determine deduplication strategy
    first = evidence[0]

    if isinstance(first, NormalizedMetric):
        return _deduplicate_metrics(evidence)
    elif isinstance(first, NormalizedLogObservation):
        return _deduplicate_logs(evidence)
    elif isinstance(first, NormalizedMongoMetadata):
        return _deduplicate_metadata(evidence)

    return evidence


def _deduplicate_metrics(metrics: list[NormalizedMetric]) -> list[NormalizedMetric]:
    """Remove duplicate metrics (same name, time window, and value)."""
    seen = set()
    deduped = []
    for metric in metrics:
        key = (metric.name, metric.start_time, metric.end_time, metric.value)
        if key not in seen:
            seen.add(key)
            deduped.append(metric)
    return deduped


def _deduplicate_logs(logs: list[NormalizedLogObservation]) -> list[NormalizedLogObservation]:
    """Remove duplicate log entries (same timestamp and content)."""
    seen = set()
    deduped = []
    for log in logs:
        # Create a hashable representation of the log content
        if isinstance(log.value, dict):
            content_key = str(sorted(log.value.items()))
        else:
            content_key = str(log.value)
        key = (log.timestamp, content_key)
        if key not in seen:
            seen.add(key)
            deduped.append(log)
    return deduped


def _deduplicate_metadata(metadata: list[NormalizedMongoMetadata]) -> list[NormalizedMongoMetadata]:
    """Remove duplicate metadata entries."""
    seen = set()
    deduped = []
    for meta in metadata:
        key = (meta.name, meta.timestamp, str(meta.value))
        if key not in seen:
            seen.add(key)
            deduped.append(meta)
    return deduped
