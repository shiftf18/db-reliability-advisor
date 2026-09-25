import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from services.analysis_service.app.config import Settings
from services.analysis_service.app.contracts.models import AnalysisPackage
from services.analysis_service.app.storage.models import FeedbackRecord


def test_mock_report_renders_and_feedback_form_creates_contract_d(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    from services.analysis_service.app.config import get_settings

    get_settings.cache_clear()
    from services.analysis_service.app.main import create_app

    app = create_app(Settings(app_env="development", database_url="sqlite://", ai_provider="mock"))
    client = TestClient(app)

    response = client.post("/api/v1/dev/mock/connection-pressure")
    assert response.status_code == 200
    report = response.json()
    report_response = client.get(f"/analyses/{report['analysisId']}/report")
    assert report_response.status_code == 200
    assert "Connection Pressure" in report_response.text
    assert 'name="analysisId"' in report_response.text
    assert 'name="verdict" value="partially_correct"' in report_response.text

    feedback_response = client.post(
        f"/api/v1/analyses/{report['analysisId']}/feedback",
        data={
            "analysisId": report["analysisId"],
            "verdict": "partially_correct",
            "comment": "Useful report",
        },
    )
    assert feedback_response.status_code == 201
    assert "Feedback recorded" in feedback_response.text
    assert app.state.feedback_repository.count_records(FeedbackRecord) == 1


def test_create_analysis_returns_contract_b_for_valid_contract_a(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    from services.analysis_service.app.config import get_settings

    get_settings.cache_clear()
    from services.analysis_service.app.main import create_app

    app = create_app(Settings(app_env="development", database_url="sqlite://", ai_provider="mock"))
    response = TestClient(app).post(
        "/api/v1/analyses",
        json={
            "target": "orders-api",
            "startTime": "2026-09-20T10:00:00Z",
            "endTime": "2026-09-20T10:10:00Z",
        },
    )

    assert response.status_code == 201
    package = AnalysisPackage.model_validate(response.json())
    assert package.analysis_id.startswith("AN-")
    assert package.target == "orders-api"
    assert package.evidence
    assert package.deterministic_findings
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "contract-b-analysis-package.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.json())
    result = TestClient(app).get(f"/api/v1/analyses/{package.analysis_id}/result")
    assert result.status_code == 200


def test_create_analysis_rejects_invalid_contract_a(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    from services.analysis_service.app.config import get_settings

    get_settings.cache_clear()
    from services.analysis_service.app.main import create_app

    app = create_app(Settings(app_env="development", database_url="sqlite://", ai_provider="mock"))
    response = TestClient(app).post(
        "/api/v1/analyses",
        json={
            "target": "orders-api",
            "startTime": "2026-09-20T10:10:00Z",
            "endTime": "2026-09-20T10:00:00Z",
        },
    )

    assert response.status_code == 422


def test_live_evidence_mode_wires_configured_adapters(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    from services.analysis_service.app.config import get_settings

    get_settings.cache_clear()
    from services.analysis_service.app.adapters.multi_source import MultiSourceAdapter
    from services.analysis_service.app.main import create_app

    app = create_app(
        Settings(
            app_env="test",
            database_url="sqlite://",
            ai_provider="mock",
            evidence_mode="live",
        )
    )

    assert isinstance(app.state.pipeline.adapter, MultiSourceAdapter)
    assert len(app.state.pipeline.adapter.adapters) == 3


def test_report_template_escapes_ai_controlled_text() -> None:
    from services.analysis_service.app.reporting.renderer import TEMPLATES

    template = TEMPLATES.env.get_template("report.html")
    rendered = template.render(
        report={
            "target": "<script>alert(1)</script>",
            "status": "warning",
            "window": {"startTime": "start", "endTime": "end"},
            "summary": "<script>alert('x')</script>",
            "analysisId": "AN-TEST",
            "sections": [],
            "limitations": [],
        }
    )
    assert "&lt;script&gt;" in rendered
    assert "<script>alert" not in rendered
