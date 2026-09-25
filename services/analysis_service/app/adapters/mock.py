from pathlib import Path

from ..contracts.models import (
    AnalysisPackage,
    AnalysisRequest,
    EvidenceObservationWindow,
)
from .base import CollectedEvidence

FIXTURE_FILES = {
    "query-regression": "scenario-a-contract-b.example.json",
    "connection-pressure": "scenario-b-contract-b.example.json",
}


class MockAdapter:
    """Loads explicit mock/illustrative evidence through the normal adapter interface."""

    def __init__(self, contract_examples_dir: Path | None = None):
        self.contract_examples_dir = contract_examples_dir or (
            Path(__file__).resolve().parents[4] / "contracts" / "examples"
        )

    def collect(
        self, request: AnalysisRequest, fixture_name: str | None = None
    ) -> CollectedEvidence:
        selected = fixture_name or "query-regression"
        try:
            filename = FIXTURE_FILES[selected]
        except KeyError as exc:
            raise ValueError(f"Unknown mock fixture: {selected}") from exc
        package = AnalysisPackage.model_validate_json(
            (self.contract_examples_dir / filename).read_text(encoding="utf-8")
        )
        duration = request.end_time - request.start_time
        timestamp = request.start_time + duration / 2
        evidence = [
            item.model_copy(
                update={
                    "timestamp": timestamp if item.kind == "event" else item.timestamp,
                    "observation_window": (
                        EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        )
                        if item.kind != "event"
                        else item.observation_window
                    ),
                }
            )
            for item in package.evidence
        ]
        return CollectedEvidence(
            evidence=evidence,
            missing_evidence=["Real production telemetry is not collected in mock mode."],
        )
