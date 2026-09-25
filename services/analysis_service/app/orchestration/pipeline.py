from datetime import timedelta
from uuid import uuid4

from services.analysis_service.app.storage import SnapshotPersistence

from ..adapters.base import EvidenceAdapter
from ..ai.base import AIProvider
from ..ai.validator import GroundingValidationError, GroundingValidator
from ..analyzers.deterministic import DeterministicAnalyzer
from ..contracts.models import AnalysisRequest, ValidatedReport
from ..evidence.builder import EvidenceBuilder
from ..reports.assembler import ReportAssembler
from ..storage.repository import AnalysisRepository


class AnalysisPipeline:
    """The one pipeline used by normal requests, both demos, and alert development hooks."""

    def __init__(
        self,
        adapter: EvidenceAdapter,
        provider: AIProvider,
        repository: AnalysisRepository,
        max_window_minutes: int = 60,
        persistence: SnapshotPersistence | None = None,
    ):
        self.adapter = adapter
        self.provider = provider
        self.repository = repository
        self.max_window = timedelta(minutes=max_window_minutes)
        self.evidence_builder = EvidenceBuilder()
        self.analyzer = DeterministicAnalyzer()
        self.validator = GroundingValidator()
        self.assembler = ReportAssembler()
        self.persistence = persistence or SnapshotPersistence()

    def run(
        self,
        request: AnalysisRequest,
        fixture_name: str = "query-regression",
    ) -> ValidatedReport:
        if request.end_time - request.start_time > self.max_window:
            maximum_minutes = self.max_window.total_seconds() / 60
            raise ValueError(
                f"Analysis window exceeds configured maximum of {maximum_minutes:g} minutes"
            )

        analysis_id = f"AN-{uuid4().hex[:12].upper()}"
        self.repository.create_run(analysis_id, request, fixture_name)
        try:
            collected = self.adapter.collect(request, fixture_name)
            package = self.evidence_builder.build(analysis_id, request, collected)
            package = package.model_copy(
                update={"deterministic_findings": self.analyzer.analyze(package.evidence)}
            )
            package_payload = package.model_dump(mode="json", by_alias=True)
            self.persistence.save_snapshot(
                analysis_id=analysis_id,
                contract_a_data=request.model_dump(mode="json", by_alias=True),
                evidence=package_payload["evidence"],
                findings=package_payload["deterministicFindings"],
                rule_version=self.analyzer.RULE_VERSION,
            )
            self.repository.save_analysis_package(analysis_id, package_payload)

            interpretation = self.provider.analyze(package)
            interpretation_payload = interpretation.model_dump(mode="json", by_alias=True)
            try:
                validated = self.validator.validate(interpretation, package)
            except GroundingValidationError as exc:
                self.repository.save_ai_attempt(
                    analysis_id,
                    self.provider.name,
                    interpretation_payload,
                    "rejected",
                    exc.errors,
                )
                raise
            self.repository.save_ai_attempt(
                analysis_id, self.provider.name, interpretation_payload, "accepted"
            )
            report = self.assembler.assemble(package, validated)
            self.repository.save_result(analysis_id, report.model_dump(mode="json", by_alias=True))
            return report
        except Exception:
            self.repository.mark_failed(analysis_id)
            raise
