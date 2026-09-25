from concurrent.futures import ThreadPoolExecutor

from ..contracts.models import AnalysisRequest
from .base import CollectedEvidence, EvidenceAdapter
from .mock import MockAdapter


class MultiSourceAdapter:
    """Collect evidence concurrently while preserving source failures and result order."""

    def __init__(self, adapters: list[EvidenceAdapter]):
        self.adapters = adapters
        self.mock_adapter = MockAdapter()

    def collect(
        self, request: AnalysisRequest, fixture_name: str | None = None
    ) -> CollectedEvidence:
        if fixture_name:
            return self.mock_adapter.collect(request, fixture_name)

        evidence = []
        missing_evidence = []
        with ThreadPoolExecutor(max_workers=len(self.adapters)) as executor:
            futures = [executor.submit(adapter.collect, request) for adapter in self.adapters]
            for adapter, future in zip(self.adapters, futures, strict=True):
                try:
                    collected = future.result()
                except Exception as exc:
                    missing_evidence.append(
                        f"Failed to collect from {type(adapter).__name__}: {exc}"
                    )
                    continue
                evidence.extend(collected.evidence)
                missing_evidence.extend(collected.missing_evidence)

        return CollectedEvidence(evidence=evidence, missing_evidence=missing_evidence)
