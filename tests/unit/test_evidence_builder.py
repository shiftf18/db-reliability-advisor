"""
Unit tests for evidence builder components (DBADV-02).

Tests for:
- Time window filtering
- Event discovery
- Sanitization
- Deduplication
- ID generation
- Missing evidence recording
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from services.analysis_service.app.contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from services.analysis_service.app.evidence.builder.deduplicator import deduplicate_evidence
from services.analysis_service.app.evidence.builder.event_discovery import discover_context_events
from services.analysis_service.app.evidence.builder.filter import filter_evidence
from services.analysis_service.app.evidence.builder.id_generator import assign_sequential_ids
from services.analysis_service.app.evidence.builder.missing_tracker import track_missing_evidence
from services.analysis_service.app.evidence.builder.sanitizer import sanitize_value
from services.analysis_service.app.evidence.normalizer import (
    NormalizedLogObservation,
    NormalizedMetric,
    NormalizedMongoMetadata,
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


def make_normalized_metric(
    *,
    name: str,
    value: Any,
    unit: str | None = None,
    source: str = "prometheus",
    source_query: str = "",
    timestamp: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> NormalizedMetric:
    """Helper to create a NormalizedMetric."""
    return NormalizedMetric(
        name=name,
        value=value,
        unit=unit,
        source=source,
        source_query=source_query,
        timestamp=timestamp,
        start_time=start_time,
        end_time=end_time,
    )


def make_normalized_log(
    *,
    name: str,
    value: Any,
    source: str = "loki",
    source_query: str = "",
    timestamp: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> NormalizedLogObservation:
    """Helper to create a NormalizedLogObservation."""
    return NormalizedLogObservation(
        name=name,
        value=value,
        source=source,
        source_query=source_query,
        timestamp=timestamp,
        start_time=start_time,
        end_time=end_time,
    )


def make_normalized_metadata(
    *,
    name: str,
    value: Any,
    source: str = "mongodb",
    source_query: str = "",
    timestamp: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> NormalizedMongoMetadata:
    """Helper to create a NormalizedMongoMetadata."""
    return NormalizedMongoMetadata(
        name=name,
        value=value,
        source=source,
        source_query=source_query,
        timestamp=timestamp,
        start_time=start_time,
        end_time=end_time,
    )


# =============================================================================
# Time Window Filtering Tests (filter.py)
# =============================================================================


def test_filter_evidence_empty_list():
    """Test filtering an empty list returns empty list."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    result = filter_evidence([], request)
    assert result == []


def test_filter_evidence_metrics_returns_same():
    """Test that metrics are returned as-is (Prometheus adapter already filters)."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    metrics = [
        make_normalized_metric(name="request_p95_ms", value=150.5, unit="ms"),
        make_normalized_metric(name="error_rate", value=0.02, unit="ratio"),
    ]
    result = filter_evidence(metrics, request)
    assert result == metrics


def test_filter_evidence_logs_returns_same():
    """Test that logs are returned as-is (no filtering applied)."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(name="mongodb_slow_operation", value={"duration": "120ms"}),
        make_normalized_log(name="mongodb_slow_operation", value={"duration": "80ms"}),
    ]
    result = filter_evidence(logs, request)
    assert result == logs


def test_filter_evidence_metadata_returns_same():
    """Test that metadata is returned as-is (no filtering applied)."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    metadata = [
        make_normalized_metadata(name="indexes", value=[{"key": {"_id": 1}}]),
        make_normalized_metadata(name="version", value="6.0.5"),
    ]
    result = filter_evidence(metadata, request)
    assert result == metadata


# =============================================================================
# Event Discovery Tests (event_discovery.py)
# =============================================================================


def test_discover_context_events_empty_list():
    """Test discovering events from empty list returns empty list."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    result = discover_context_events([], request)
    assert result == []


def test_discover_context_events_finds_deployment():
    """Test discovering deployment events."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "deployment", "service": "orders-api", "version": "1.2.3"},
        ),
        make_normalized_log(
            name="mongodb_slow_operation",
            value={"duration": "120ms"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["event"] == "deployment"


def test_discover_context_events_finds_restart():
    """Test discovering service restart events."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "restart", "service": "orders-api"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["event"] == "restart"


def test_discover_context_events_finds_scenario_marker():
    """Test discovering scenario marker events."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={
                "event": "scenario_marker",
                "service": "orders-api",
                "scenario": "query_regression",
            },
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["event"] == "scenario_marker"


def test_discover_context_events_finds_alert_trigger():
    """Test discovering alert trigger events."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "alert_trigger", "service": "orders-api", "alert": "high_latency"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["event"] == "alert_trigger"


def test_discover_context_events_filters_by_service():
    """Test that events for other services are filtered out."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "deployment", "service": "other-service"},
        ),
        make_normalized_log(
            name="context_event",
            value={"event": "deployment", "service": "orders-api"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["service"] == "orders-api"


def test_discover_context_events_allows_none_service():
    """Test that events with no service field are included."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "deployment"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1


def test_discover_context_events_skips_non_dict_values():
    """Test that logs with non-dict values are skipped."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value="just a string message",
        ),
        make_normalized_log(
            name="context_event",
            value={"event": "deployment", "service": "orders-api"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1


def test_discover_context_events_skips_unknown_event_types():
    """Test that unknown event types are skipped."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    logs = [
        make_normalized_log(
            name="context_event",
            value={"event": "unknown_event", "service": "orders-api"},
        ),
        make_normalized_log(
            name="context_event",
            value={"event": "deployment", "service": "orders-api"},
        ),
    ]
    result = discover_context_events(logs, request)
    assert len(result) == 1
    assert result[0].value["event"] == "deployment"


# =============================================================================
# Sanitization Tests (sanitizer.py)
# =============================================================================


def test_sanitize_metric_returns_same():
    """Test that metrics are returned unchanged (no sensitive data expected)."""
    metric = make_normalized_metric(name="request_p95_ms", value=150.5, unit="ms")
    result = sanitize_value(metric)
    assert result == metric


def test_sanitize_log_dict_redacts_sensitive_keys():
    """Test that sensitive keys in log dict are redacted."""
    log = make_normalized_log(
        name="mongodb_slow_operation",
        value={
            "duration": "120ms",
            "password": "secret123",
            "api_key": "key123",
            "normal_field": "value",
        },
    )
    result = sanitize_value(log)
    assert result.value["password"] == "[REDACTED]"
    assert result.value["api_key"] == "[REDACTED]"
    assert result.value["normal_field"] == "value"
    assert result.value["duration"] == "120ms"


def test_sanitize_log_dict_case_insensitive():
    """Test that sensitive key detection is case-insensitive."""
    log = make_normalized_log(
        name="test",
        value={
            "PASSWORD": "secret",
            "PassWord": "secret2",
            "api_key": "key",  # SENSITIVE_KEYS has "api_key" not "apikey"
        },
    )
    result = sanitize_value(log)
    assert result.value["PASSWORD"] == "[REDACTED]"
    assert result.value["PassWord"] == "[REDACTED]"
    assert result.value["api_key"] == "[REDACTED]"


def test_sanitize_log_dict_nested():
    """Test that nested dicts are sanitized recursively."""
    log = make_normalized_log(
        name="test",
        value={
            "user": {
                "password": "secret",
                "name": "john",
            },
            "config": {
                "api_key": "key123",
            },
        },
    )
    result = sanitize_value(log)
    assert result.value["user"]["password"] == "[REDACTED]"
    assert result.value["user"]["name"] == "john"
    assert result.value["config"]["api_key"] == "[REDACTED]"


def test_sanitize_metadata_dict_list():
    """Test that metadata with list of dicts is sanitized."""
    metadata = make_normalized_metadata(
        name="configs",
        value=[
            {"password": "secret1"},
            {"api_key": "key1"},
            "plain string",
        ],
    )
    result = sanitize_value(metadata)
    assert result.value[0]["password"] == "[REDACTED]"
    assert result.value[1]["api_key"] == "[REDACTED]"
    assert result.value[2] == "plain string"


def test_sanitize_log_string_redacts_patterns():
    """Test that sensitive patterns in strings are redacted."""
    log = make_normalized_log(
        name="test",
        value='password=secret123 api_key="key456" email=user@example.com',
    )
    result = sanitize_value(log)
    assert "[REDACTED]" in result.value
    assert "secret123" not in result.value
    assert "key456" not in result.value
    assert "user@example.com" not in result.value


def test_sanitize_metadata_dict():
    """Test that metadata dict values are sanitized."""
    metadata = make_normalized_metadata(
        name="config",
        value={
            "username": "admin",
            "password": "secret",
            "host": "localhost",
        },
    )
    result = sanitize_value(metadata)
    assert result.value["username"] == "[REDACTED]"
    assert result.value["password"] == "[REDACTED]"
    assert result.value["host"] == "[REDACTED]"


def test_sanitize_metadata_list():
    """Test that metadata list values are sanitized."""
    metadata = make_normalized_metadata(
        name="configs",
        value=[
            {"password": "secret1"},
            {"api_key": "key1"},
        ],
    )
    result = sanitize_value(metadata)
    assert result.value[0]["password"] == "[REDACTED]"
    assert result.value[1]["api_key"] == "[REDACTED]"


# =============================================================================
# Deduplication Tests (deduplicator.py)
# =============================================================================


def test_deduplicate_evidence_empty_list():
    """Test deduplicating empty list returns empty list."""
    result = deduplicate_evidence([])
    assert result == []


def test_deduplicate_metrics_removes_duplicates():
    """Test that duplicate metrics (same name, time window, value) are removed."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    start = datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    metrics = [
        make_normalized_metric(
            name="request_p95_ms",
            value=150.5,
            unit="ms",
            timestamp=ts,
            start_time=start,
            end_time=end,
        ),
        make_normalized_metric(
            name="request_p95_ms",
            value=150.5,
            unit="ms",
            timestamp=ts,
            start_time=start,
            end_time=end,
        ),  # duplicate
        make_normalized_metric(
            name="error_rate",
            value=0.02,
            unit="ratio",
            timestamp=ts,
            start_time=start,
            end_time=end,
        ),
    ]
    result = deduplicate_evidence(metrics)
    assert len(result) == 2
    assert result[0].name == "request_p95_ms"
    assert result[1].name == "error_rate"


def test_deduplicate_metrics_keeps_different_values():
    """Test that metrics with different values are kept."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    start = datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    metrics = [
        make_normalized_metric(
            name="request_p95_ms",
            value=150.5,
            unit="ms",
            timestamp=ts,
            start_time=start,
            end_time=end,
        ),
        make_normalized_metric(
            name="request_p95_ms",
            value=200.0,
            unit="ms",
            timestamp=ts,
            start_time=start,
            end_time=end,
        ),  # different value
    ]
    result = deduplicate_evidence(metrics)
    assert len(result) == 2


def test_deduplicate_logs_removes_duplicates():
    """Test that duplicate logs (same timestamp and content) are removed."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    logs = [
        make_normalized_log(
            name="slow_op", value={"duration": "120ms", "ns": "test"}, timestamp=ts
        ),
        make_normalized_log(
            name="slow_op", value={"duration": "120ms", "ns": "test"}, timestamp=ts
        ),  # duplicate
        make_normalized_log(name="slow_op", value={"duration": "80ms", "ns": "test"}, timestamp=ts),
    ]
    result = deduplicate_evidence(logs)
    assert len(result) == 2


def test_deduplicate_logs_keeps_different_content():
    """Test that logs with different content are kept."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    logs = [
        make_normalized_log(name="slow_op", value={"duration": "120ms"}, timestamp=ts),
        make_normalized_log(
            name="slow_op", value={"duration": "80ms"}, timestamp=ts
        ),  # different content
    ]
    result = deduplicate_evidence(logs)
    assert len(result) == 2


def test_deduplicate_logs_string_values():
    """Test deduplication with string log values."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    logs = [
        make_normalized_log(name="log", value="error: connection failed", timestamp=ts),
        make_normalized_log(
            name="log", value="error: connection failed", timestamp=ts
        ),  # duplicate
        make_normalized_log(name="log", value="warning: slow query", timestamp=ts),
    ]
    result = deduplicate_evidence(logs)
    assert len(result) == 2


def test_deduplicate_metadata_removes_duplicates():
    """Test that duplicate metadata entries are removed."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    metadata = [
        make_normalized_metadata(name="indexes", value=[{"key": {"_id": 1}}], timestamp=ts),
        make_normalized_metadata(
            name="indexes", value=[{"key": {"_id": 1}}], timestamp=ts
        ),  # duplicate
        make_normalized_metadata(name="version", value="6.0.5", timestamp=ts),
    ]
    result = deduplicate_evidence(metadata)
    assert len(result) == 2


# =============================================================================
# ID Generation Tests (id_generator.py)
# =============================================================================


def test_assign_sequential_ids_empty_list():
    """Test assigning IDs to empty list returns empty list."""
    result = assign_sequential_ids([])
    assert result == []


def test_assign_sequential_ids_single_item():
    """Test assigning ID to single item."""
    evidence = [
        Evidence(
            id="old-id",
            kind="metric_window",
            name="test",
            value=1,
            source=EvidenceSource(system="prometheus"),
        )
    ]
    result = assign_sequential_ids(evidence)
    assert len(result) == 1
    assert result[0].id == "E1"


def test_assign_sequential_ids_multiple_items():
    """Test assigning sequential IDs to multiple items."""
    evidence = [
        Evidence(
            id="old-1",
            kind="metric_window",
            name="test1",
            value=1,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="old-2",
            kind="metric_window",
            name="test2",
            value=2,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="old-3",
            kind="metric_window",
            name="test3",
            value=3,
            source=EvidenceSource(system="prometheus"),
        ),
    ]
    result = assign_sequential_ids(evidence)
    assert result[0].id == "E1"
    assert result[1].id == "E2"
    assert result[2].id == "E3"


def test_assign_sequential_ids_returns_same_list():
    """Test that the same list object is returned (in-place modification)."""
    evidence = [
        Evidence(
            id="old-1",
            kind="metric_window",
            name="test1",
            value=1,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="old-2",
            kind="metric_window",
            name="test2",
            value=2,
            source=EvidenceSource(system="prometheus"),
        ),
    ]
    result = assign_sequential_ids(evidence)
    assert result is evidence  # Same object


# =============================================================================
# Missing Evidence Recording Tests (missing_tracker.py)
# =============================================================================


def test_track_missing_evidence_empty():
    """Test tracking missing evidence with no evidence items."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    result = track_missing_evidence(
        evidence_items=[],
        adapter_missing=[],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    assert "Insufficient evidence collected for meaningful analysis" in result


def test_track_missing_evidence_with_adapter_missing():
    """Test that adapter-reported missing evidence is included."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="request_p95_ms",
            value=100,
            source=EvidenceSource(system="prometheus"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=["prometheus: query timeout"],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    assert "prometheus: query timeout" in result


def test_track_missing_evidence_query_regression_scenario():
    """Test missing evidence detection for query regression scenario."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    # Has request_p95_ms and documents_examined -> query regression scenario
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="request_p95_ms",
            value=100,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="E2",
            kind="event",
            name="documents_examined",
            value=1000,
            source=EvidenceSource(system="loki"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=[],
        request=request,
        query_regression_evidence={
            "request_p95_ms",
            "documents_examined",
            "error_rate",
            "plan_summary",
        },
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    # Should detect missing error_rate and plan_summary
    assert any("error_rate" in m for m in result)
    assert any("plan_summary" in m for m in result)


def test_track_missing_evidence_connection_pressure_scenario():
    """Test missing evidence detection for connection pressure scenario."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    # Has connection_utilization_percent -> connection pressure scenario
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="connection_utilization_percent",
            value=85,
            source=EvidenceSource(system="prometheus"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=[],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={
            "connection_utilization_percent",
            "max_connections",
            "active_connections",
        },
    )
    # Should detect missing max_connections and active_connections
    assert any("max_connections" in m for m in result)
    assert any("active_connections" in m for m in result)


def test_track_missing_evidence_insufficient_evidence():
    """Test that insufficient evidence warning is added when < 3 items."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="request_p95_ms",
            value=100,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="E2",
            kind="event",
            name="documents_examined",
            value=1000,
            source=EvidenceSource(system="loki"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=[],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    assert "Insufficient evidence collected for meaningful analysis" in result


def test_track_missing_evidence_sufficient_evidence_no_warning():
    """Test that no insufficient evidence warning when >= 3 items."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="request_p95_ms",
            value=100,
            source=EvidenceSource(system="prometheus"),
        ),
        Evidence(
            id="E2",
            kind="event",
            name="documents_examined",
            value=1000,
            source=EvidenceSource(system="loki"),
        ),
        Evidence(
            id="E3",
            kind="metadata",
            name="version",
            value="6.0.5",
            source=EvidenceSource(system="mongodb"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=[],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    assert "Insufficient evidence collected for meaningful analysis" not in result


def test_track_missing_evidence_unknown_scenario():
    """Test that no expected evidence is checked for unknown scenario."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2024, 1, 1, 11, 55, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    # Has neither query regression nor connection pressure indicators
    evidence = [
        Evidence(
            id="E1",
            kind="metric_window",
            name="some_other_metric",
            value=100,
            source=EvidenceSource(system="prometheus"),
        ),
    ]
    result = track_missing_evidence(
        evidence_items=evidence,
        adapter_missing=[],
        request=request,
        query_regression_evidence={"request_p95_ms", "documents_examined"},
        connection_pressure_evidence={"connection_utilization_percent"},
    )
    # Should only have adapter missing (empty) and possibly insufficient evidence
    assert len(result) == 1  # Only the insufficient evidence warning
    assert "Insufficient evidence collected for meaningful analysis" in result
