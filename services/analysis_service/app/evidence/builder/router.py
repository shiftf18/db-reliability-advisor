"""
Evidence Builder Wrapper for DBADV-02.

This is the main entry point that detects whether incoming evidence is:
1. Raw adapter output (needs full processing pipeline)
2. Pre-formatted mock evidence (pass through with minimal processing)

It delegates to the appropriate handler to keep the code clean and maintainable.
"""

from __future__ import annotations

from ...adapters.base import CollectedEvidence
from ...contracts.models import AnalysisPackage, AnalysisRequest
from .mock_evidence_pipeline import MockEvidenceHandler
from .real_evidence_pipeline import RawEvidenceProcessor


class EvidenceBuilder:
    """
    Main evidence builder that routes to the appropriate processor.

    This wrapper detects the evidence format and delegates to either:
    - RawEvidenceProcessor: For real adapter output (Prometheus, Loki, MongoDB)
    - MockEvidenceHandler: For pre-formatted mock evidence from test fixtures
    """

    def __init__(self):
        self.raw_processor = RawEvidenceProcessor()
        self.mock_handler = MockEvidenceHandler()

    def build(
        self,
        analysis_id: str,
        request: AnalysisRequest,
        collected: CollectedEvidence,
    ) -> AnalysisPackage:
        """
        Build an AnalysisPackage from collected evidence.

        Automatically detects evidence format and applies appropriate processing.

        Args:
            analysis_id: Unique identifier for this analysis
            request: The analysis request containing target and time window
            collected: Raw evidence collected from all adapters

        Returns:
            AnalysisPackage with structured evidence ready for deterministic analysis
        """
        # Detect if evidence is already in final Contract B format (mock)
        if self._is_mock_format(collected.evidence):
            return self.mock_handler.build(analysis_id, request, collected)
        else:
            return self.raw_processor.build(analysis_id, request, collected)

    def _is_mock_format(self, evidence_list: list) -> bool:
        """
        Detect if evidence is already in mock/final format.

        Mock evidence has:
        - Sequential IDs like E1, E2, E3...
        - Proper evidence kinds (metric_comparison, query_comparison, etc.)
        - Source system = "mock"
        """
        if not evidence_list:
            return False

        # Check first few items for mock characteristics
        for item in evidence_list[:3]:
            # Mock evidence has sequential E1, E2, E3... IDs
            if not (hasattr(item, "id") and isinstance(item.id, str) and item.id.startswith("E")):
                return False
            # Mock evidence has proper evidence kinds
            if not hasattr(item, "kind") or item.kind not in (
                "event",
                "metric_comparison",
                "metric_window",
                "query_comparison",
                "query_window",
                "query_plan",
                "metadata",
            ):
                return False
            # Mock evidence typically has source.system = "mock"
            if (
                hasattr(item, "source")
                and hasattr(item.source, "system")
                and item.source.system == "mock"
            ):
                return True

        return False
