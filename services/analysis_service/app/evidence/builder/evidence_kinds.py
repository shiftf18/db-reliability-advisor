"""
Evidence Kinds Builder for DBADV-02.

Constructs evidence kinds (metric_comparison, query_comparison, query_plan, etc.)
from normalized evidence for deterministic analysis.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from statistics import median
from typing import Any
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
    evidence.extend(_build_metric_comparisons(metrics, events, request))
    evidence.extend(_build_query_comparisons(logs, events, request))
    evidence.extend(_build_query_plans(logs, events, request))
    evidence.extend(_build_metadata_evidence(metadata, request))
    evidence.extend(_build_event_evidence(events, request))
    evidence.extend(_build_metric_windows(metrics, events, request))
    evidence.extend(_build_query_windows(logs, request))

    return evidence


def _event_split(events: list[NormalizedLogObservation]) -> datetime | None:
    timestamps = [event.timestamp for event in events if event.timestamp is not None]
    return min(timestamps) if timestamps else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _metric_samples(value: Any) -> list[tuple[datetime, float]]:
    if not isinstance(value, dict) or not isinstance(value.get("samples"), list):
        return []
    samples = []
    for sample in value["samples"]:
        if not isinstance(sample, dict):
            continue
        timestamp = _timestamp(sample.get("timestamp"))
        try:
            sample_value = float(sample["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp is not None:
            samples.append((timestamp, sample_value))
    return samples


def _metric_comparison_value(value: Any, split: datetime | None) -> dict[str, float] | None:
    if isinstance(value, dict) and "before" in value and "after" in value:
        try:
            return {"before": float(value["before"]), "after": float(value["after"])}
        except (TypeError, ValueError):
            return None
    if split is None:
        return None
    samples = _metric_samples(value)
    before = [sample for timestamp, sample in samples if timestamp < split]
    after = [sample for timestamp, sample in samples if timestamp >= split]
    if not before or not after:
        return None
    return {"before": median(before), "after": median(after)}


def _build_metric_comparisons(
    metrics: list[NormalizedMetric],
    events: list[NormalizedLogObservation],
    request: AnalysisRequest,
) -> list[Evidence]:
    """Build metric_comparison evidence from before/after metrics."""
    evidence = []

    split = _event_split(events)
    for metric in metrics:
        comparison = _metric_comparison_value(metric.value, split)
        if comparison is not None:
            evidence.append(
                Evidence(
                    id=str(uuid4()),  # Will be reassigned later
                    kind="metric_comparison",
                    name=metric.name,
                    value=comparison,
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
    logs: list[NormalizedLogObservation],
    events: list[NormalizedLogObservation],
    request: AnalysisRequest,
) -> list[Evidence]:
    """Build query_comparison evidence from slow-operation logs."""
    evidence = []
    slow_logs = [
        log
        for log in logs
        if isinstance(log.value, dict)
        and (log.name == "mongodb_slow_operation" or "documentsExamined" in log.value)
    ]
    if not slow_logs:
        return []

    split = _event_split(events)
    before_logs = [log for log in slow_logs if split and log.timestamp and log.timestamp < split]
    after_logs = [log for log in slow_logs if split and log.timestamp and log.timestamp >= split]
    has_comparison = bool(before_logs and after_logs)
    for name, field in (
        ("documents_examined", "documentsExamined"),
        ("documents_returned", "documentsReturned"),
    ):
        before_values = _numeric_log_values(before_logs, field)
        after_values = _numeric_log_values(after_logs, field)
        all_values = _numeric_log_values(slow_logs, field)
        if has_comparison and before_values and after_values:
            kind = "query_comparison"
            value = {"before": median(before_values), "after": median(after_values)}
        elif all_values:
            kind = "query_window"
            value = median(all_values)
        else:
            continue
        evidence.append(_query_evidence(kind, name, value, slow_logs[0], request))

    before_ratios = _scan_ratios(before_logs)
    after_ratios = _scan_ratios(after_logs)
    all_ratios = _scan_ratios(slow_logs)
    if has_comparison and before_ratios and after_ratios:
        evidence.append(
            _query_evidence(
                "query_comparison",
                "scan_ratio",
                {"before": median(before_ratios), "after": median(after_ratios)},
                slow_logs[0],
                request,
            )
        )
    elif all_ratios:
        evidence.append(
            _query_evidence("query_window", "scan_ratio", median(all_ratios), slow_logs[0], request)
        )

    return evidence


def _numeric_log_values(logs: list[NormalizedLogObservation], field: str) -> list[float]:
    values = []
    for log in logs:
        try:
            values.append(float(log.value[field]))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def _scan_ratios(logs: list[NormalizedLogObservation]) -> list[float]:
    ratios = []
    for log in logs:
        try:
            examined = float(log.value["documentsExamined"])
            returned = max(float(log.value["documentsReturned"]), 1)
        except (KeyError, TypeError, ValueError):
            continue
        ratios.append(examined / returned)
    return ratios


def _query_evidence(
    kind: str,
    name: str,
    value: Any,
    log: NormalizedLogObservation,
    request: AnalysisRequest,
) -> Evidence:
    return Evidence(
        id=str(uuid4()),
        kind=kind,
        name=name,
        value=value,
        source=EvidenceSource(system=log.source, query=log.source_query),
        observation_window=EvidenceObservationWindow(
            start_time=request.start_time,
            end_time=request.end_time,
        ),
    )


def _build_query_plans(
    logs: list[NormalizedLogObservation],
    events: list[NormalizedLogObservation],
    request: AnalysisRequest,
) -> list[Evidence]:
    """Build query_plan evidence from slow-operation logs."""
    plan_logs = [
        log
        for log in logs
        if isinstance(log.value, dict)
        and (log.value.get("planSummary") or log.value.get("plan_summary"))
    ]
    if not plan_logs:
        return []

    split = _event_split(events)
    before = [
        str(log.value.get("planSummary") or log.value.get("plan_summary"))
        for log in plan_logs
        if split and log.timestamp and log.timestamp < split
    ]
    after = [
        str(log.value.get("planSummary") or log.value.get("plan_summary"))
        for log in plan_logs
        if split and log.timestamp and log.timestamp >= split
    ]
    if before and after:
        value = {"before": _mode(before), "after": _mode(after)}
    else:
        plans = [
            str(log.value.get("planSummary") or log.value.get("plan_summary")) for log in plan_logs
        ]
        value = {"observed": _mode(plans), "stable": len(set(plans)) == 1}
    return [_query_evidence("query_plan", "query_plan", value, plan_logs[0], request)]


def _mode(values: list[str]) -> str:
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value))


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
                observation_window=EvidenceObservationWindow(
                    start_time=event.start_time or request.start_time,
                    end_time=event.end_time or request.end_time,
                ),
                timestamp=event.timestamp,
            )
        )

    return evidence


def _build_metric_windows(
    metrics: list[NormalizedMetric],
    events: list[NormalizedLogObservation],
    request: AnalysisRequest,
) -> list[Evidence]:
    """Build metric_window evidence for window-based metrics."""
    evidence = []
    split = _event_split(events)

    for metric in metrics:
        if _metric_comparison_value(metric.value, split) is not None:
            continue
        samples = [value for _, value in _metric_samples(metric.value)]
        value = median(samples) if samples else metric.value
        evidence.append(
            Evidence(
                id=str(uuid4()),
                kind="metric_window",
                name=metric.name,
                value=value,
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
