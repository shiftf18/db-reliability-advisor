from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from services.analysis_service.app.contracts.models import (
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from services.analysis_service.app.evidence.normalizer import (
    NormalizedLogObservation,
    NormalizedMetric,
    NormalizedMongoMetadata,
    normalize_evidence_list,
    normalize_loki_evidence,
    normalize_mongodb_evidence,
    normalize_prometheus_evidence,
)


def make_evidence(
    *,
    id: str | None = None,
    kind: str,
    name: str,
    value: Any,
    unit: str | None = None,
    system: str,
    query: str | None = None,
    timestamp: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Evidence:
    """Helper to create an Evidence object."""
    if id is None:
        id = str(uuid4())
    if start_time is None and end_time is None:
        observation_window = None
    else:
        observation_window = EvidenceObservationWindow(
            start_time=start_time or datetime.now(UTC),
            end_time=end_time or datetime.now(UTC),
        )
    return Evidence(
        id=id,
        kind=kind,
        name=name,
        value=value,
        unit=unit,
        source=EvidenceSource(system=system, query=query),
        observation_window=observation_window,
        timestamp=timestamp,
    )


def test_normalize_prometheus_evidence():
    ev = make_evidence(
        kind="metric_window",
        name="request_p95_ms",
        value=150.5,
        unit="ms",
        system="prometheus",
        query=(
            "histogram_quantile(0.95, "
            'sum(rate(http_request_duration_seconds_bucket{service="api"}[5m])) by (le))'
        ),
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    norm = normalize_prometheus_evidence(ev)
    assert isinstance(norm, NormalizedMetric)
    assert norm.name == "request_p95_ms"
    assert norm.value == 150.5
    assert norm.unit == "ms"
    assert norm.source == "prometheus"
    assert norm.source_query == ev.source.query
    assert norm.timestamp == ev.timestamp
    assert norm.start_time == ev.observation_window.start_time
    assert norm.end_time == ev.observation_window.end_time


def test_normalize_loki_evidence():
    ev = make_evidence(
        kind="event",
        name="mongodb_slow_operation",
        value={"duration": "120ms", "namespace": "test"},
        unit=None,
        system="loki",
        query=(
            '{job="mongodb"} | json | '
            "timestamp, namespace, operation, duration, documentsExamined, "
            "documentsReturned, keysExamined, planSummary"
        ),
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    norm = normalize_loki_evidence(ev)
    assert isinstance(norm, NormalizedLogObservation)
    assert norm.name == "mongodb_slow_operation"
    assert norm.value == {"duration": "120ms", "namespace": "test"}
    assert norm.unit is None
    assert norm.source == "loki"
    assert norm.source_query == ev.source.query
    assert norm.timestamp == ev.timestamp
    assert norm.start_time == ev.observation_window.start_time
    assert norm.end_time == ev.observation_window.end_time


def test_normalize_mongodb_evidence():
    ev = make_evidence(
        kind="metadata",
        name="version",
        value="6.0.5",
        unit=None,
        system="mongodb",
        query="db.buildInfo().version",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    norm = normalize_mongodb_evidence(ev)
    assert isinstance(norm, NormalizedMongoMetadata)
    assert norm.name == "version"
    assert norm.value == "6.0.5"
    assert norm.unit is None
    assert norm.source == "mongodb"
    assert norm.source_query == ev.source.query
    assert norm.timestamp == ev.timestamp
    assert norm.start_time == ev.observation_window.start_time
    assert norm.end_time == ev.observation_window.end_time


def test_normalize_evidence_list():
    ev1 = make_evidence(
        kind="metric_window",
        name="request_p95_ms",
        value=100.0,
        unit="ms",
        system="prometheus",
        query=(
            "histogram_quantile(0.95, "
            'sum(rate(http_request_duration_seconds_bucket{service="api"}[5m])) by (le))'
        ),
    )
    ev2 = make_evidence(
        kind="event",
        name="mongodb_slow_operation",
        value={"duration": "50ms"},
        unit=None,
        system="loki",
        query=('{job="mongodb"} | json | timestamp, namespace, operation, duration'),
    )
    ev3 = make_evidence(
        kind="metadata",
        name="indexes",
        value=[{"v": 2, "key": {"_id": 1}}],
        unit=None,
        system="mongodb",
        query="db.orders.getIndexes()",
    )
    ev4 = make_evidence(
        kind="metric_comparison",
        name="unknown",
        value="something",
        unit=None,
        system="prometheus",  # allowed system but we only handle metric_window for prometheus
        query="some query",
    )  # Should be ignored

    metrics, logs, metadata = normalize_evidence_list([ev1, ev2, ev3, ev4])

    assert len(metrics) == 1
    assert isinstance(metrics[0], NormalizedMetric)
    assert metrics[0].name == "request_p95_ms"

    assert len(logs) == 1
    assert isinstance(logs[0], NormalizedLogObservation)
    assert logs[0].name == "mongodb_slow_operation"

    assert len(metadata) == 1
    assert isinstance(metadata[0], NormalizedMongoMetadata)
    assert metadata[0].name == "indexes"

    # Ensure the unknown evidence was ignored
    assert len(metrics) + len(logs) + len(metadata) == 3
