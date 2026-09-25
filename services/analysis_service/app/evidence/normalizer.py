"""
Evidence Normalization Layer for DBADV-02.

This module implements Step 6 of the DBADV-02 implementation plan:
"Normalization Layer: Convert adapter outputs to internal canonical models".

It defines three normalized data models:
- NormalizedMetric: for Prometheus metrics (e.g., request p95 latency, error rate)
- NormalizedLogObservation: for Loki log events (e.g., slow-operation logs, deployment events)
- NormalizedMongoMetadata: for MongoDB metadata (e.g., indexes, connection limit, version)

And provides functions to convert raw Evidence objects (as produced by adapters)
into these normalized forms, preserving provenance (source.system and source.query)
and performing any necessary unit conversions (e.g., seconds to milliseconds).

The normalization process is designed to be lossless with respect to the data
needed for downstream deterministic analysis, while standardizing the format
so that the analyzer can work with a consistent interface regardless of the
original data source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..contracts.models import Evidence


class NormalizedMetric(BaseModel):
    """
    Normalized representation of a metric from Prometheus or similar monitoring systems.

    This model standardizes metric data so that the deterministic analyzer can
    process metrics from different sources (though currently only Prometheus is
    implemented) using the same interface.

    Fields:
    - name: Identifier for the metric (e.g., "request_p95_ms", "error_rate")
    - timestamp: Single point-in-time timestamp (if applicable)
    - start_time: Start of the observation window (for range metrics)
    - end_time: End of the observation window (for range metrics)
    - value: The numeric value of the metric
    - unit: Unit of measurement (e.g., "ms" for milliseconds, "ratio" for error rate)
    - source: The system that produced the metric (e.g., "prometheus")
    - source_query: The exact query used to retrieve the metric (for provenance)
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    timestamp: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    value: Any
    unit: str | None = None
    source: str  # e.g., "prometheus"
    source_query: str  # the actual PromQL used


class NormalizedLogObservation(BaseModel):
    """
    Normalized representation of a log observation from Loki or similar log systems.

    This model standardizes log data (both structured and unstructured) so that
    the deterministic analyzer can process logs from different sources using
    the same interface.

    Fields:
    - name: Identifier for the log type (e.g., "mongodb_slow_operation", "context_event")
    - timestamp: Timestamp of the log event
    - start_time: Start of the observation window (if applicable)
    - end_time: End of the observation window (if applicable)
    - value: The log data (parsed as dict if JSON, or raw string if not)
    - unit: Unit of measurement (typically None for logs)
    - source: The system that produced the log (e.g., "loki")
    - source_query: The exact LogQL query used to retrieve the logs (for provenance)
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    timestamp: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    value: Any  # parsed log data (dict) or raw message (str)
    unit: str | None = None
    source: str  # e.g., "loki"
    source_query: str  # the actual LogQL used


class NormalizedMongoMetadata(BaseModel):
    """
    Normalized representation of MongoDB metadata.

    This model standardizes metadata retrieved from MongoDB so that the
    deterministic analyzer can process it using the same interface as metrics
    and logs.

    Fields:
    - name: Identifier for the metadata type (e.g., "indexes", "connection_limit", "version")
    - timestamp: Timestamp when the metadata was collected
    - start_time: Start of the observation window (if applicable)
    - end_time: End of the observation window (if applicable)
    - value: The metadata value (can be complex, e.g., list of index documents)
    - unit: Unit of measurement (typically None for metadata counts/versions)
    - source: The system that produced the metadata (e.g., "mongodb")
    - source_query: The exact MongoDB command used to retrieve the metadata (for provenance)
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    timestamp: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    value: Any
    unit: str | None = None
    source: str  # e.g., "mongodb"
    source_query: str  # the actual MongoDB command used


def _extract_time_windows(
    evidence: Evidence,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """
    Extract timestamp, start_time, and end_time from an Evidence object.

    The Evidence object may contain either:
    - A single timestamp (for point-in-time observations)
    - An observation_window with start_time and end_time (for range observations)
    - Both (in which case timestamp may represent the event time within the window)

    This helper function returns a tuple of (timestamp, start_time, end_time),
    where any of the three may be None if not present in the original evidence.

    Args:
        evidence: The Evidence object to extract time information from

    Returns:
        A tuple (timestamp, start_time, end_time) where each element is either
        a datetime object or None
    """
    # Extract the single timestamp if present
    ts = evidence.timestamp

    # Extract the observation window if present
    if evidence.observation_window:
        start = evidence.observation_window.start_time
        end = evidence.observation_window.end_time
    else:
        start = None
        end = None

    return ts, start, end


def normalize_prometheus_evidence(evidence: Evidence) -> NormalizedMetric:
    """
    Convert a Prometheus Evidence object to a NormalizedMetric.

    This function assumes that the input evidence meets the following criteria:
    - evidence.kind == "metric_window" (indicating it's a metric observation)
    - evidence.source.system == "prometheus" (indicating it came from Prometheus)

    The function extracts the time information (timestamp, start_time, end_time)
    from the evidence and maps the remaining fields to the NormalizedMetric model.
    The source and source_query are preserved for provenance tracking.

    No unit conversion is performed here for Prometheus metrics because:
    - Latency metrics are already converted to milliseconds in the adapter
    - Error rate is already a ratio (0-1) in the adapter
    If additional unit conversions were needed, they would be performed here.

    Args:
        evidence: The Evidence object from the Prometheus adapter

    Returns:
        A NormalizedMetric object with the same data in a standardized format
    """
    # Extract time information from the evidence
    ts, start, end = _extract_time_windows(evidence)

    # Create and return the normalized metric
    return NormalizedMetric(
        name=evidence.name,
        timestamp=ts,
        start_time=start,
        end_time=end,
        value=evidence.value,
        unit=evidence.unit,
        source=evidence.source.system,  # Should be "prometheus"
        source_query=evidence.source.query or "",  # Preserve the actual PromQL
    )


def normalize_loki_evidence(evidence: Evidence) -> NormalizedLogObservation:
    """
    Convert a Loki Evidence object to a NormalizedLogObservation.

    This function assumes that the input evidence meets the following criteria:
    - evidence.kind == "event" (indicating it's a log event)
    - evidence.source.system == "loki" (indicating it came from Loki)

    The function extracts the time information (timestamp, start_time, end_time)
    from the evidence and maps the remaining fields to the NormalizedLogObservation
    model. The source and source_query are preserved for provenance tracking.

    No additional processing is performed on the log value here because:
    - The Loki adapter already parses JSON log lines into dictionaries
    - Non-JSON log lines are preserved as raw strings in the "raw_message" field
    - Timestamp conversion to seconds is already handled in the adapter
    - Deduplication is already handled in the adapter

    Args:
        evidence: The Evidence object from the Loki adapter

    Returns:
        A NormalizedLogObservation object with the same data in a standardized format
    """
    # Extract time information from the evidence
    ts, start, end = _extract_time_windows(evidence)

    # Create and return the normalized log observation
    return NormalizedLogObservation(
        name=evidence.name,
        timestamp=ts,
        start_time=start,
        end_time=end,
        value=evidence.value,  # Already processed by adapter (dict or raw string)
        unit=evidence.unit,  # Typically None for logs
        source=evidence.source.system,  # Should be "loki"
        source_query=evidence.source.query or "",  # Preserve the actual LogQL
    )


def normalize_mongodb_evidence(evidence: Evidence) -> NormalizedMongoMetadata:
    """
    Convert a MongoDB Evidence object to a NormalizedMongoMetadata.

    This function assumes that the input evidence meets the following criteria:
    - evidence.kind == "metadata" (indicating it's metadata)
    - evidence.source.system == "mongodb" (indicating it came from MongoDB)

    The function extracts the time information (timestamp, start_time, end_time)
    from the evidence and maps the remaining fields to the NormalizedMongoMetadata
    model. The source and source_query are preserved for provenance tracking.

    No unit conversion is performed here for MongoDB metadata because:
    - Indexes are returned as raw documents (no unit)
    - Connection limit is a count (no unit)
    - Version is a string (no unit)
    If additional unit conversions were needed, they would be performed here.

    Args:
        evidence: The Evidence object from the MongoDB adapter

    Returns:
        A NormalizedMongoMetadata object with the same data in a standardized format
    """
    # Extract time information from the evidence
    ts, start, end = _extract_time_windows(evidence)

    # Create and return the normalized metadata
    return NormalizedMongoMetadata(
        name=evidence.name,
        timestamp=ts,
        start_time=start,
        end_time=end,
        value=evidence.value,
        unit=evidence.unit,
        source=evidence.source.system,  # Should be "mongodb"
        source_query=evidence.source.query or "",  # Preserve the actual MongoDB command
    )


def normalize_evidence_list(
    evidence_list: list[Evidence],
) -> tuple[list[NormalizedMetric], list[NormalizedLogObservation], list[NormalizedMongoMetadata]]:
    """
    Normalize a list of Evidence objects into three separate lists:
    metrics, logs, and metadata.

    This is the main entry point for the normalization layer. It takes a list
    of raw Evidence objects (as returned by the EvidenceBuilder after collecting
    from all adapters) and separates them into three categories based on their
    source system and kind:

    1. Metrics: source.system == "prometheus" AND evidence.kind == "metric_window"
    2. Logs: source.system == "loki" AND evidence.kind == "event"
    3. Metadata: source.system == "mongodb" AND evidence.kind == "metadata"

    Any evidence that does not match one of these three combinations is ignored
    (silently skipped). This design allows the system to be extensible - if new
    adapter types are added in the future, they can be accommodated by adding
    additional branches to this dispatch logic.

    The function preserves all data from the original evidence objects while
    converting them to the appropriate normalized format for downstream processing
    by the deterministic analyzer.

    Args:
        evidence_list: A list of Evidence objects from the EvidenceBuilder

    Returns:
        A tuple of three lists:
        - List of NormalizedMetric objects (from Prometheus)
        - List of NormalizedLogObservation objects (from Loki)
        - List of NormalizedMongoMetadata objects (from MongoDB)
    """
    # Initialize empty lists for each normalized type
    metrics: list[NormalizedMetric] = []
    logs: list[NormalizedLogObservation] = []
    metadata: list[NormalizedMongoMetadata] = []

    # Process each evidence object in the input list
    for evidence in evidence_list:
        # Dispatch to the appropriate normalization function based on
        # the source system and evidence kind. This ensures that each
        # type of evidence is converted to its corresponding normalized form.

        # Prometheus metrics: kind="metric_window", system="prometheus"
        if evidence.source.system == "prometheus" and evidence.kind == "metric_window":
            metrics.append(normalize_prometheus_evidence(evidence))

        # Loki logs: kind="event", system="loki"
        elif evidence.source.system == "loki" and evidence.kind == "event":
            logs.append(normalize_loki_evidence(evidence))

        # MongoDB metadata: kind="metadata", system="mongodb"
        elif evidence.source.system == "mongodb" and evidence.kind == "metadata":
            metadata.append(normalize_mongodb_evidence(evidence))

        # Any other combination is ignored (could be logged as a warning in production)
        else:
            # For now, we silently skip unknown evidence types.
            # In a production system, we might want to log this for debugging.
            pass

    # Return the three lists as a tuple
    return metrics, logs, metadata
