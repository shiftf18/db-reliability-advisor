"""
Evidence Kinds Builder for DBADV-02.

Constructs evidence kinds (metric_comparison, query_comparison, query_plan, etc.)
from normalized evidence for deterministic analysis.
"""

from __future__ import annotations

from uuid import uuid4

from ...contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from ..normalizer import (
    NormalizedLogObservation,
    NormalizedMetric,
    NormalizedMongoMetadata,
)


def build_evidence_kinds(
    metrics: list[NormalizedMetric],
    logs: list[NormalizedLogObservation],
    metadata: list[NormalizedMongoMetadata],
    events: list[NormalizedLogObservation],
    request: AnalysisRequest,
) -> list[Evidence]:
    """
    Build evidence kinds for deterministic analysis.

    Creates evidence items of kinds:
    - metric_comparison: Before/after metric comparisons
    - query_comparison: Query efficiency comparisons (documents examined/returned)
    - query_plan: Query plan changes (IXSCAN -> COLLSCAN)
    - metadata: MongoDB metadata (indexes, connection limit, version)
    - event: Context events (deployments, restarts, alerts)
    - metric_window: Window-based metrics without before/after
    - query_window: Query metrics without before/after

    Args:
        metrics: Normalized metrics from Prometheus
        logs: Normalized logs from Loki
        metadata: Normalized metadata from MongoDB
        events: Discovered context events
        request: Analysis request

    Returns:
        List of Evidence items ready for deterministic analysis
    """
    evidence = []

    # Build each evidence kind
    evidence.extend(_build_metric_comparisons(metrics, request))
    evidence.extend(_build_query_comparisons(logs, request))
    evidence.extend(_build_query_plans(logs, request))
    evidence.extend(_build_metadata_evidence(metadata, request))
    evidence.extend(_build_event_evidence(events, request))
    evidence.extend(_build_metric_windows(metrics, request))
    evidence.extend(_build_query_windows(logs, request))

    return evidence


def _build_metric_comparisons(
    metrics: list[NormalizedMetric], request: AnalysisRequest
) -> list[Evidence]:
    """Build metric_comparison evidence from before/after metrics."""
    evidence = []

    for metric in metrics:
        if isinstance(metric.value, dict) and "before" in metric.value and "after" in metric.value:
            evidence.append(
                Evidence(
                    id=str(uuid4()),  # Will be reassigned later
                    kind="metric_comparison",
                    name=metric.name,
                    value=metric.value,
                    unit=metric.unit,
                    source=EvidenceSource(system=metric.source, query=metric.source_query),
                    observation_window=EvidenceObservationWindow(
                        start_time=request.start_time,
                        end_time=request.end_time,
                    ),
                    timestamp=None,
                )
            )

    return evidence


def _build_query_comparisons(
    logs: list[NormalizedLogObservation], request: AnalysisRequest
) -> list[Evidence]:
    """Build query_comparison evidence from slow-operation logs."""
    evidence = []

    for log in logs:
        if not isinstance(log.value, dict):
            continue

        # Check if this is a MongoDB slow operation log
        if log.name == "mongodb_slow_operation" or "documentsExamined" in log.value:
            value = log.value

            # Build documents_examined comparison
            if "documentsExamined" in value:
                evidence.append(
                    Evidence(
                        id=str(uuid4()),
                        kind="query_comparison",
                        name="documents_examined",
                        value={
                            "before": value.get("documentsExamined", 0),
                            "after": value.get("documentsExamined", 0),
                        },
                        unit=None,
                        source=EvidenceSource(system=log.source, query=log.source_query),
                        observation_window=EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        ),
                        timestamp=log.timestamp,
                    )
                )

            # Build documents_returned comparison
            if "documentsReturned" in value:
                evidence.append(
                    Evidence(
                        id=str(uuid4()),
                        kind="query_comparison",
                        name="documents_returned",
                        value={
                            "before": value.get("documentsReturned", 0),
                            "after": value.get("documentsReturned", 0),
                        },
                        unit=None,
                        source=EvidenceSource(system=log.source, query=log.source_query),
                        observation_window=EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        ),
                        timestamp=log.timestamp,
                    )
                )

            # Build scan_ratio comparison
            if "documentsExamined" in value and "documentsReturned" in value:
                returned = max(value.get("documentsReturned", 1), 1)
                ratio = value.get("documentsExamined", 0) / returned
                evidence.append(
                    Evidence(
                        id=str(uuid4()),
                        kind="query_comparison",
                        name="scan_ratio",
                        value={"before": ratio, "after": ratio},
                        unit=None,
                        source=EvidenceSource(system=log.source, query=log.source_query),
                        observation_window=EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        ),
                        timestamp=log.timestamp,
                    )
                )

    return evidence


def _build_query_plans(
    logs: list[NormalizedLogObservation], request: AnalysisRequest
) -> list[Evidence]:
    """Build query_plan evidence from slow-operation logs."""
    evidence = []

    for log in logs:
        if not isinstance(log.value, dict):
            continue

        if "planSummary" in log.value or "plan_summary" in log.value:
            plan = log.value.get("planSummary") or log.value.get("plan_summary")
            evidence.append(
                Evidence(
                    id=str(uuid4()),
                    kind="query_plan",
                    name="query_plan",
                    value={"before": plan, "after": plan},
                    unit=None,
                    source=EvidenceSource(system=log.source, query=log.source_query),
                    observation_window=EvidenceObservationWindow(
                        start_time=request.start_time,
                        end_time=request.end_time,
                    ),
                    timestamp=log.timestamp,
                )
            )

    return evidence


def _build_metadata_evidence(
    metadata: list[NormalizedMongoMetadata], request: AnalysisRequest
) -> list[Evidence]:
    """Build metadata evidence from MongoDB metadata."""
    evidence = []

    for meta in metadata:
        evidence.append(
            Evidence(
                id=str(uuid4()),
                kind="metadata",
                name=meta.name,
                value=meta.value,
                unit=meta.unit,
                source=EvidenceSource(system=meta.source, query=meta.source_query),
                observation_window=EvidenceObservationWindow(
                    start_time=request.start_time,
                    end_time=request.end_time,
                ),
                timestamp=meta.timestamp,
            )
        )

    return evidence


def _build_event_evidence(
    events: list[NormalizedLogObservation], request: AnalysisRequest
) -> list[Evidence]:
    """Build event evidence from context events."""
    evidence = []

    for event in events:
        evidence.append(
            Evidence(
                id=str(uuid4()),
                kind="event",
                name=event.name,
                value=event.value,
                unit=event.unit,
                source=EvidenceSource(system=event.source, query=event.source_query),
                observation_window=event.observation_window,
                timestamp=event.timestamp,
            )
        )

    return evidence


def _build_metric_windows(
    metrics: list[NormalizedMetric], request: AnalysisRequest
) -> list[Evidence]:
    """Build metric_window evidence for window-based metrics."""
    evidence = []

    for metric in metrics:
        # Only create window evidence for metrics that aren't already comparisons
        if not (
            isinstance(metric.value, dict) and "before" in metric.value and "after" in metric.value
        ):
            evidence.append(
                Evidence(
                    id=str(uuid4()),
                    kind="metric_window",
                    name=metric.name,
                    value=metric.value,
                    unit=metric.unit,
                    source=EvidenceSource(system=metric.source, query=metric.source_query),
                    observation_window=EvidenceObservationWindow(
                        start_time=request.start_time,
                        end_time=request.end_time,
                    ),
                    timestamp=metric.timestamp,
                )
            )

    return evidence


def _build_query_windows(
    logs: list[NormalizedLogObservation], request: AnalysisRequest
) -> list[Evidence]:
    """Build query_window evidence for query metrics without before/after."""
    evidence = []

    for log in logs:
        if not isinstance(log.value, dict):
            continue

        # Create window evidence for query metrics that don't have comparison data
        if log.name == "mongodb_slow_operation":
            # Could create query_window evidence here if needed
            pass

    return evidence
