from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from ..contracts.models import (
    AnalysisAccepted,
    AnalysisRequest,
    AnalysisStatus,
    ValidatedReport,
)
from ..orchestration.pipeline import AnalysisPipeline
from ..reporting.renderer import TEMPLATES

# Contract A API Endpoint
# Objective: Create the POST /api/v1/analyses endpoint that accepts analysis requests
# Done:
#   - Router created
#   - POST handler implemented with validation of Contract A
#   - Analysis ID generated in format AN-[random string]
#   - Request passed to orchestrator for processing
#   - Error handling for invalid Contract A
# Note:
#   - Returns 201 Created (synchronous processing) as per MVP allowance
#   - Unit tests for endpoint validation not yet implemented
router = APIRouter(prefix="/api/v1")
dev_router = APIRouter(prefix="/api/v1/dev/mock")
pages_router = APIRouter()


def _pipeline(request: Request) -> AnalysisPipeline:
    return request.app.state.pipeline


@pages_router.get("/", response_class=HTMLResponse)
def report_index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="index.html",
        context={"reports": request.app.state.repository.list_reports()},
    )


@pages_router.get("/analyses/{analysis_id}/report", response_class=HTMLResponse)
def get_analysis_report(analysis_id: str, request: Request) -> HTMLResponse:
    report = request.app.state.repository.get_result(analysis_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Analysis report not found")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="report.html",
        context={"report": report},
    )


# POST handler for analyses endpoint
@router.post("/analyses", response_model=AnalysisAccepted, status_code=status.HTTP_201_CREATED)
def create_analysis(payload: AnalysisRequest, request: Request) -> AnalysisAccepted:
    try:
        report = _pipeline(request).run(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc  # Error handling for invalid Contract A
    return AnalysisAccepted(analysis_id=report.analysis_id, status="completed")


@router.get("/analyses/{analysis_id}", response_model=AnalysisStatus)
def get_analysis(analysis_id: str, request: Request) -> AnalysisStatus:
    run = request.app.state.repository.get_run(analysis_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return AnalysisStatus.model_validate(run)


@router.get("/analyses/{analysis_id}/result", response_model=ValidatedReport)
def get_analysis_result(analysis_id: str, request: Request) -> ValidatedReport:
    result = request.app.state.repository.get_result(analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis result not found")
    return ValidatedReport.model_validate(result)


def _mock_request() -> AnalysisRequest:
    end_time = datetime.now(UTC).replace(second=0, microsecond=0)
    return AnalysisRequest(
        target="orders-api",
        start_time=end_time - timedelta(minutes=10),
        end_time=end_time,
    )


@dev_router.post("/query-regression", response_model=ValidatedReport)
def run_query_regression(request: Request) -> ValidatedReport:
    return _pipeline(request).run(_mock_request(), fixture_name="query-regression")


@dev_router.post("/connection-pressure", response_model=ValidatedReport)
def run_connection_pressure(request: Request) -> ValidatedReport:
    return _pipeline(request).run(_mock_request(), fixture_name="connection-pressure")


@dev_router.post("/alertmanager", response_model=ValidatedReport)
def receive_mock_alert(request: Request, payload: dict[str, Any]) -> ValidatedReport:
    """Development bridge proving alerts enter through the same Contract A pipeline."""
    del payload  # Controlled foundation hook; DBADV-01 will map real labels and timestamps.
    return _pipeline(request).run(_mock_request(), fixture_name="connection-pressure")
