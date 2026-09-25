"""Evidence Builder Package for DBADV-02.

This package provides a modular evidence building pipeline with support for
both raw adapter evidence and pre-formatted mock evidence.
"""

from .router import EvidenceBuilder

__all__ = ["EvidenceBuilder"]
