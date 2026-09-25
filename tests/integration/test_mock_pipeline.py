from datetime import UTC, datetime

import pytest

from services.analysis_service.app.adapters.base import CollectedEvidence
from services.analysis_service.app.adapters.mock import MockAdapter
from services.analysis_service.app.ai.mock_provider import MockAIProvider
from services.analysis_service.app.analyzers.deterministic import DeterministicAnalyzer
from services.analysis_service.app.contracts.models import AnalysisRequest
from services.analysis_service.app.evidence.builder import EvidenceBuilder
from services.analysis_service.app.orchestration.pipeline import AnalysisPipeline
from services.analysis_service.app.storage.database import (
    create_database_engine,
    initialize_database,
)
from services.analysis_service.app.storage.models import (
    AIAttempt,
    AnalysisResult,
    AnalysisRun,
    DeterministicResult,
    EvidenceSnapshot,
)
from services.analysis_service.app.storage.persistence import SnapshotPersistence
from services.analysis_service.app.storage.repository import AnalysisRepository


class SnapshotCheckingProvider(MockAIProvider):
    def __init__(self, persistence: SnapshotPersistence) -> None:
        self.persistence = persistence

    def analyze(self, package):
        snapshot = self.persistence.get_snapshot(package.analysis_id)
        assert snapshot is not None
        package_payload = package.model_dump(mode="json", by_alias=True)
        assert snapshot["evidence"] == package_payload["evidence"]
        assert snapshot["findings"] == package_payload["deterministicFindings"]
        return super().analyze(package)


def request_at(hour: int) -> AnalysisRequest:
    return AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, hour, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, hour, 10, tzinfo=UTC),
    )


def test_both_scenarios_use_same_pipeline_and_persist_all_stages(tmp_path) -> None:
    engine = create_database_engine("sqlite://")
    initialize_database(engine)
    repository = AnalysisRepository(engine)
    persistence = SnapshotPersistence(tmp_path / "audit.db")
    provider = SnapshotCheckingProvider(persistence)
    pipeline = AnalysisPipeline(MockAdapter(), provider, repository, persistence=persistence)

    query_report = pipeline.run(request_at(10), "query-regression")
    connection_report = pipeline.run(request_at(11), "connection-pressure")

    assert query_report.sections[0].title == "Query Efficiency Regression"
    assert connection_report.sections[0].title == "Connection Pressure"
    assert query_report.analysis_id != connection_report.analysis_id
    assert repository.get_result(query_report.analysis_id) is not None
    assert repository.get_result(connection_report.analysis_id) is not None
    assert persistence.get_snapshot(query_report.analysis_id) is not None
    assert persistence.get_snapshot(connection_report.analysis_id) is not None
    for model in [AnalysisRun, EvidenceSnapshot, DeterministicResult, AIAttempt, AnalysisResult]:
        assert repository.count_records(model) == 2


def test_insufficient_evidence_is_persisted_without_ai_call(tmp_path) -> None:
    class UnavailableAdapter:
        def collect(self, request, fixture_name=None):
            return CollectedEvidence(
                evidence=[],
                missing_evidence=["Prometheus unavailable", "Loki unavailable"],
            )

    class ProviderMustNotRun:
        name = "must-not-run"

        def analyze(self, package):
            raise AssertionError("AI must not be called without deterministic findings")

    engine = create_database_engine("sqlite://")
    initialize_database(engine)
    repository = AnalysisRepository(engine)
    persistence = SnapshotPersistence(tmp_path / "audit.db")
    pipeline = AnalysisPipeline(
        UnavailableAdapter(),
        ProviderMustNotRun(),
        repository,
        persistence=persistence,
    )

    report = pipeline.run(request_at(10))
    snapshot = persistence.get_snapshot(report.analysis_id)
    run = repository.get_run(report.analysis_id)

    assert report.status == "insufficient_data"
    assert "Prometheus unavailable" in report.limitations
    assert repository.get_result(report.analysis_id) is not None
    assert run["status"] == "completed"
    assert snapshot is not None
    assert snapshot["evidence"] == []
    assert snapshot["findings"] == []
    assert repository.count_records(AIAttempt) == 0


def test_pipeline_enforces_configured_maximum_window(tmp_path) -> None:
    engine = create_database_engine("sqlite://")
    initialize_database(engine)
    pipeline = AnalysisPipeline(
        MockAdapter(),
        MockAIProvider(),
        AnalysisRepository(engine),
        max_window_minutes=5,
        persistence=SnapshotPersistence(tmp_path / "audit.db"),
    )
    with pytest.raises(ValueError, match="configured maximum"):
        pipeline.run(request_at(10), "query-regression")


def test_connection_scenario_cites_stable_plan_as_contradicting_evidence() -> None:
    request = request_at(11)
    package = EvidenceBuilder().build(
        "AN-CONTRADICTION",
        request,
        MockAdapter().collect(request, "connection-pressure"),
    )
    findings = DeterministicAnalyzer().analyze(package.evidence)
    package = package.model_copy(update={"deterministic_findings": findings})
    interpretation = MockAIProvider().analyze(package)
    hypothesis = interpretation.sections[0].hypothesis
    evidence = {item.id: item for item in package.evidence}

    assert {"E5", "E6"}.issubset(hypothesis.contradicting_evidence_ids)
    assert evidence["E5"].value["before"] == evidence["E5"].value["after"] == "IXSCAN"
    assert evidence["E6"].value["after"] - evidence["E6"].value["before"] <= 2
