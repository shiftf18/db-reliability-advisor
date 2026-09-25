 
"""
Mock Evidence Handler for DBADV-02.

Handles pre-formatted mock evidence from test fixtures.
This evidence is already in the final Contract B format and just needs
minimal validation and pass-through.
"""

from __future__ import annotations

from typing import Any

from ...adapters.base import CollectedEvidence
from ...contracts.models import (
    AnalysisPackage,
    AnalysisRequest,
    AnalysisWindow,
    Evidence,
    EvidenceObservationWindow,
)


class MockEvidenceHandler:
    """
    Handles mock evidence that's already in final format.
    
    The mock adapter returns evidence that matches the Contract B schema
    exactly, so we just need to:
    1. Validate the evidence structure
    2. Ensure IDs are sequential (E1, E2, ...)
    3. Update timestamps/observation windows to match the request
    4. Track missing evidence
    """
    
    def build(
        self,
        analysis_id: str,
        request: AnalysisRequest,
        collected: CollectedEvidence,
    ) -> AnalysisPackage:
        """
        Build AnalysisPackage from mock evidence.
        
        Args:
            analysis_id: Unique identifier for this analysis
            request: The analysis request containing target and time window
            collected: Pre-formatted mock evidence
            
        Returns:
            AnalysisPackage with mock evidence
        """
        evidence = list(collected.evidence)
        
        # Update timestamps and observation windows to match the request
        evidence = self._align_to_request_window(evidence, request)
        
        # Ensure sequential IDs (E1, E2, E3...)
        evidence = self._ensure_sequential_ids(evidence)
        
        # Track missing evidence
        missing_evidence = list(collected.missing_evidence)
        
        return AnalysisPackage(
            analysis_id=analysis_id,
            target=request.target,
            window=AnalysisWindow(start_time=request.start_time, end_time=request.end_time),
            evidence=evidence,
            deterministic_findings=[],
            missing_evidence=missing_evidence,
        )
    
    def _align_to_request_window(
        self, evidence: list[Evidence], request: AnalysisRequest
    ) -> list[Evidence]:
        """Align evidence timestamps and observation windows to the request window."""
        aligned = []
        duration = request.end_time - request.start_time
        midpoint = request.start_time + duration / 2
        
        for item in evidence:
            # Create a copy with updated time fields
            updates: dict[str, Any] = {}
            
            # For events, update timestamp to midpoint
            if item.kind == "event":
                updates["timestamp"] = midpoint
            
            # For non-events, update observation window
            if item.kind != "event":
                updates["observation_window"] = EvidenceObservationWindow(
                    start_time=request.start_time,
                    end_time=request.end_time,
                )
            
            if updates:
                aligned.append(item.model_copy(update=updates))
            else:
                aligned.append(item)
        
        return aligned
    
    def _ensure_sequential_ids(self, evidence: list[Evidence]) -> list[Evidence]:
        """Ensure evidence IDs are sequential (E1, E2, E3...)."""
        for i, item in enumerate(evidence, 1):
            expected_id = f"E{i}"
            if item.id != expected_id:
                # Create a copy with the correct ID
                evidence[i] = item.model_copy(update={"id": expected_id})
        return evidence