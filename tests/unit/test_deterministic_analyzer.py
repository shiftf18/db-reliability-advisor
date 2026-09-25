from datetime import UTC, datetime

from services.analysis_service.app.adapters.mock import MockAdapter
from services.analysis_service.app.analyzers.deterministic import DeterministicAnalyzer
from services.analysis_service.app.contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)


def test_missing_named_evidence_returns_no_partial_rule_findings() -> None:
    findings = DeterministicAnalyzer().analyze([])

    assert findings == []


def test_zero_baselines_do_not_crash_or_divide_by_zero() -> None:
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    adjusted = [
        item.model_copy(update={"value": {"before": 0, "after": 50}})
        if item.name == "documents_returned"
        else item
        for item in evidence
    ]

    findings = DeterministicAnalyzer().analyze(adjusted)

    assert findings[0].result["percentIncrease"] == 400
    assert all(finding.rule != "scan_ratio_change" for finding in findings)


# --- Test each rule with sample evidence ---


def test_latency_regression_rule() -> None:
    """Test latency_percent_change rule calculates correctly."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    latency_finding = next(f for f in findings if f.rule == "latency_percent_change")
    assert latency_finding.result["percentIncrease"] == 400
    assert latency_finding.result["beforeMs"] == 200.0
    assert latency_finding.result["afterMs"] == 1000.0
    assert latency_finding.result["thresholdPercent"] == 50.0
    assert latency_finding.evidence_ids == ["E2"]


def test_scan_ratio_change_rule() -> None:
    """Test scan_ratio_change rule calculates correctly."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    scan_finding = next(f for f in findings if f.rule == "scan_ratio_change")
    assert scan_finding.result["before"] == 20.0
    assert scan_finding.result["after"] == 4000.0
    assert scan_finding.evidence_ids == ["E3", "E4"]


def test_query_plan_change_rule() -> None:
    """Test query_plan_change rule detects plan change."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    plan_finding = next(f for f in findings if f.rule == "query_plan_change")
    assert plan_finding.result["before"] == "IXSCAN"
    assert plan_finding.result["after"] == "COLLSCAN"
    assert plan_finding.evidence_ids == ["E5"]


def test_connection_pressure_rule() -> None:
    """Test connection_pressure rule calculates correctly."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 11, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 11, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "connection-pressure").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    cp_finding = next(f for f in findings if f.rule == "connection_pressure")
    assert cp_finding.result["beforePercent"] == 25.0
    assert cp_finding.result["afterPercent"] == 92.0
    assert cp_finding.result["thresholdPercent"] == 90.0
    assert cp_finding.evidence_ids == ["E1", "E4"]


def test_query_plan_stable_rule() -> None:
    """Test query_plan_stable rule for contradicting evidence."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 11, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 11, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "connection-pressure").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    stable_finding = next(f for f in findings if f.rule == "query_plan_stable")
    assert stable_finding.result["plan"] == "IXSCAN"
    assert stable_finding.result["scanRatioChangePercent"] == 5
    assert stable_finding.evidence_ids == ["E5", "E6"]


# --- Test threshold boundaries ---


def test_latency_threshold_boundary() -> None:
    """Test latency finding includes threshold from settings."""
    from services.analysis_service.app.config import get_settings

    settings = get_settings()
    assert settings.latency_regression_threshold_percent == 50.0

    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    latency_finding = next(f for f in findings if f.rule == "latency_percent_change")
    assert (
        latency_finding.result["thresholdPercent"] == settings.latency_regression_threshold_percent
    )


def test_connection_pressure_threshold_boundary() -> None:
    """Test connection pressure finding includes threshold from settings."""
    from services.analysis_service.app.config import get_settings

    settings = get_settings()
    assert settings.connection_pressure_threshold_percent == 90.0

    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 11, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 11, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "connection-pressure").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    cp_finding = next(f for f in findings if f.rule == "connection_pressure")
    assert cp_finding.result["thresholdPercent"] == settings.connection_pressure_threshold_percent


# --- Test missing evidence handling ---


def test_empty_evidence_returns_empty() -> None:
    """Test empty evidence list returns empty findings."""
    findings = DeterministicAnalyzer().analyze([])
    assert findings == []


def test_partial_evidence_latency_only() -> None:
    """Test partial evidence (only latency) returns only latency finding."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    latency_only = [e for e in evidence if e.name == "request_p95_ms"]
    findings = DeterministicAnalyzer().analyze(latency_only)

    assert len(findings) == 1
    assert findings[0].rule == "latency_percent_change"


def test_missing_required_evidence_returns_partial() -> None:
    """Test missing required evidence returns what it can."""
    # Create minimal evidence with only latency
    evidence = [
        Evidence(
            id="E1",
            kind="metric_comparison",
            name="request_p95_ms",
            value={"before": 100, "after": 200},
            unit="ms",
            source=EvidenceSource(system="mock"),
            observation_window=EvidenceObservationWindow(
                start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
                end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
            ),
        )
    ]
    findings = DeterministicAnalyzer().analyze(evidence)
    assert len(findings) == 1
    assert findings[0].rule == "latency_percent_change"


def test_zero_baseline_scan_ratio_skipped() -> None:
    """Test zero baseline for documents_returned skips scan_ratio_change."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    adjusted = [
        item.model_copy(update={"value": {"before": 0, "after": 50}})
        if item.name == "documents_returned"
        else item
        for item in evidence
    ]

    findings = DeterministicAnalyzer().analyze(adjusted)
    assert findings[0].result["percentIncrease"] == 400
    assert all(finding.rule != "scan_ratio_change" for finding in findings)


# --- Test evidence ID linking ---


def test_all_findings_have_evidence_ids() -> None:
    """Test all findings reference correct evidence IDs."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    for finding in findings:
        assert finding.evidence_ids
        assert all(isinstance(eid, str) for eid in finding.evidence_ids)

    # Verify specific evidence ID mappings
    latency_finding = next(f for f in findings if f.rule == "latency_percent_change")
    assert latency_finding.evidence_ids == ["E2"]

    scan_finding = next(f for f in findings if f.rule == "scan_ratio_change")
    assert set(scan_finding.evidence_ids) == {"E3", "E4"}

    plan_finding = next(f for f in findings if f.rule == "query_plan_change")
    assert plan_finding.evidence_ids == ["E5"]


def test_connection_scenario_evidence_ids() -> None:
    """Test connection pressure scenario evidence ID linking."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 11, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 11, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "connection-pressure").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    for finding in findings:
        assert finding.evidence_ids
        assert all(isinstance(eid, str) for eid in finding.evidence_ids)

    cp_finding = next(f for f in findings if f.rule == "connection_pressure")
    assert set(cp_finding.evidence_ids) == {"E1", "E4"}

    latency_finding = next(f for f in findings if f.rule == "latency_percent_change")
    assert latency_finding.evidence_ids == ["E2"]

    stable_finding = next(f for f in findings if f.rule == "query_plan_stable")
    assert set(stable_finding.evidence_ids) == {"E5", "E6"}


def test_finding_ids_are_sequential() -> None:
    """Test finding IDs are sequential (D1, D2, D3...)."""
    request = AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )
    evidence = MockAdapter().collect(request, "query-regression").evidence
    findings = DeterministicAnalyzer().analyze(evidence)

    for i, finding in enumerate(findings):
        assert finding.id == f"D{i + 1}"
