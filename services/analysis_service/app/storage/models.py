from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RuleVersion:
    version_id: str
    description: str
    created_at: str


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    analysis_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fixture_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.analysis_id"), index=True)
    package_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DeterministicResult(Base):
    __tablename__ = "deterministic_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.analysis_id"), index=True)
    findings_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AIAttempt(Base):
    __tablename__ = "ai_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.analysis_id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), primary_key=True
    )
    report_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.analysis_id"), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(120))
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
