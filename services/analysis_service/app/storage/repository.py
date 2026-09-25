from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ..contracts.models import AnalysisRequest
from .models import (
    AIAttempt,
    AnalysisResult,
    AnalysisRun,
    DeterministicResult,
    EvidenceSnapshot,
)


class AnalysisRepository:
    """Small persistence boundary for audit and replay data."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create_run(
        self, analysis_id: str, request: AnalysisRequest, fixture_name: str | None
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                AnalysisRun(
                    analysis_id=analysis_id,
                    status="running",
                    request_payload=request.model_dump(mode="json", by_alias=True),
                    fixture_name=fixture_name,
                )
            )
            session.commit()

    def save_analysis_package(self, analysis_id: str, package: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.add(EvidenceSnapshot(analysis_id=analysis_id, package_payload=package))
            session.add(
                DeterministicResult(
                    analysis_id=analysis_id,
                    findings_payload=package["deterministicFindings"],
                )
            )
            session.commit()

    def save_ai_attempt(
        self,
        analysis_id: str,
        provider: str,
        response: dict[str, Any],
        validation_status: str,
        validation_errors: list[str] | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                AIAttempt(
                    analysis_id=analysis_id,
                    provider=provider,
                    response_payload=response,
                    validation_status=validation_status,
                    validation_errors=validation_errors or [],
                )
            )
            session.commit()

    def save_result(self, analysis_id: str, report: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            session.add(AnalysisResult(analysis_id=analysis_id, report_payload=report))
            run = session.get(AnalysisRun, analysis_id)
            if run:
                run.status = "completed"
            session.commit()

    def mark_failed(self, analysis_id: str) -> None:
        with Session(self.engine) as session:
            run = session.get(AnalysisRun, analysis_id)
            if run:
                run.status = "failed"
                session.commit()

    def get_run(self, analysis_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            run = session.get(AnalysisRun, analysis_id)
            if run is None:
                return None
            return {
                "analysisId": run.analysis_id,
                "status": run.status,
                "request": run.request_payload,
                "fixtureName": run.fixture_name,
            }

    def get_result(self, analysis_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            result = session.get(AnalysisResult, analysis_id)
            return result.report_payload if result else None

    def count_records(self, model: type[Any]) -> int:
        with Session(self.engine) as session:
            return len(session.scalars(select(model)).all())

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(AnalysisResult.report_payload)
                .order_by(AnalysisResult.created_at.desc())
                .limit(limit)
            )
            return [row[0] for row in rows]
