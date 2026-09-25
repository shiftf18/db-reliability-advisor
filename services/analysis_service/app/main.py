from fastapi import FastAPI
from prometheus_client import make_asgi_app

from .adapters.loki import LokiAdapter
from .adapters.mock import MockAdapter
from .adapters.mongodb import MongoMetadataAdapter
from .adapters.multi_source import MultiSourceAdapter
from .adapters.prometheus import PrometheusAdapter
from .ai.gemini_provider import GeminiAIProvider
from .ai.mock_provider import MockAIProvider
from .api import analyses, feedback, health
from .config import Settings, get_settings
from .orchestration.analyzer import AnalysisOrchestrator
from .storage.database import create_database_engine, initialize_database
from .storage.feedback_repository import FeedbackRepository
from .storage.repository import AnalysisRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    runtime_settings.validate_provider_configuration()

    engine = create_database_engine(runtime_settings.database_url)
    initialize_database(engine)
    repository = AnalysisRepository(engine)
    feedback_repository = FeedbackRepository(engine)
    provider = (
        GeminiAIProvider(runtime_settings.gemini_api_key, runtime_settings.gemini_model)
        if runtime_settings.ai_provider == "gemini"
        else MockAIProvider()
    )
    evidence_adapter = (
        MultiSourceAdapter(
            [
                PrometheusAdapter(runtime_settings.prometheus_url),
                LokiAdapter(runtime_settings.loki_url),
                MongoMetadataAdapter(runtime_settings.mongodb_uri),
            ]
        )
        if runtime_settings.evidence_mode == "live"
        else MockAdapter()
    )
    pipeline = AnalysisOrchestrator(
        adapter=evidence_adapter,
        provider=provider,
        repository=repository,
        max_window_minutes=runtime_settings.max_analysis_window_minutes,
    )

    app = FastAPI(title="Database Reliability Advisor", version="0.1.0")
    app.state.repository = repository
    app.state.feedback_repository = feedback_repository
    app.state.pipeline = pipeline
    app.state.settings = runtime_settings
    app.include_router(health.router)
    app.include_router(analyses.pages_router)
    app.include_router(analyses.router)
    app.include_router(feedback.router)
    if runtime_settings.app_env == "development":
        app.include_router(analyses.dev_router)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()
