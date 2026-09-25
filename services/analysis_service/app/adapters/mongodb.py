from uuid import uuid4

from pymongo import MongoClient

from ..contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from .base import CollectedEvidence


class MongoMetadataAdapter:
    """
    Adapter for collecting read-only MongoDB metadata.
    Implements: Fetch read-only MongoDB metadata (indexes, connection limits, version).
    """

    def __init__(self, uri: str):
        self.uri = uri

    def ping(self) -> bool:
        """Check if MongoDB is reachable."""
        try:
            with MongoClient(self.uri, serverSelectionTimeoutMS=2000) as client:
                return bool(client.admin.command("ping")["ok"])
        except Exception:
            return False

    def collect(
        self, request: AnalysisRequest, fixture_name: str | None = None
    ) -> CollectedEvidence:
        """
        Collect read-only MongoDB metadata: indexes, connection limit, version.
        Returns CollectedEvidence with list of Evidence objects.
        """
        evidence_list = []
        missing_evidence = []

        # If fixture_name is provided, we could load mock data for testing.
        # For simplicity, we skip fixture loading in this implementation.
        # In a real test environment, you would load from fixture files.
        # mock mode uses MockAdapter instead
        if fixture_name:
            # For now, return empty evidence when fixture mode is requested.
            # This allows tests to proceed without actual MongoDB.
            return CollectedEvidence(evidence=[], missing_evidence=[])

        try:
            with MongoClient(self.uri) as client:
                # Get the default database from the URI.
                db = client.get_default_database()
                if db is None:
                    # Fallback to the database name from the URI (if parsing failed).
                    # Extract database name from mongodb://host:port/dbname
                    db_name = self.uri.split("/")[-1].split("?")[0]
                    if not db_name:
                        db_name = "reliability_demo"  # default from config
                    db = client[db_name]

                # Collection name as per the step description (orders collection).
                collection = db["orders"]

                # 1. Current indexes: db.orders.getIndexes()
                try:
                    indexes = list(collection.list_indexes())
                    evidence = Evidence(
                        id=str(uuid4()),
                        kind="metadata",
                        name="indexes",
                        value=indexes,
                        unit=None,
                        source=EvidenceSource(system="mongodb", query="db.orders.getIndexes()"),
                        observation_window=EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        ),
                        timestamp=None,
                    )
                    evidence_list.append(evidence)
                except Exception as exc:
                    missing_evidence.append(f"Failed to get indexes: {exc}")

                # 2. Connection limit: db.serverStatus().connections (if available)
                try:
                    server_status = client.admin.command("serverStatus")
                    connections = server_status.get("connections")
                    if connections is not None:
                        evidence = Evidence(
                            id=str(uuid4()),
                            kind="metadata",
                            name="connection_limit",
                            value=connections,
                            unit=None,
                            source=EvidenceSource(
                                system="mongodb",
                                query='db.adminCommand("serverStatus").connections',
                            ),
                            observation_window=EvidenceObservationWindow(
                                start_time=request.start_time,
                                end_time=request.end_time,
                            ),
                            timestamp=None,
                        )
                        evidence_list.append(evidence)
                except Exception as exc:
                    missing_evidence.append(f"Failed to get connection limit: {exc}")

                # 3. MongoDB version: db.buildInfo().version
                try:
                    build_info = db.command("buildInfo")
                    version = build_info.get("version")
                    if version is not None:
                        evidence = Evidence(
                            id=str(uuid4()),
                            kind="metadata",
                            name="version",
                            value=version,
                            unit=None,
                            source=EvidenceSource(system="mongodb", query="db.buildInfo().version"),
                            observation_window=EvidenceObservationWindow(
                                start_time=request.start_time,
                                end_time=request.end_time,
                            ),
                            timestamp=None,
                        )
                        evidence_list.append(evidence)
                except Exception as exc:
                    missing_evidence.append(f"Failed to get MongoDB version: {exc}")

        except Exception as exc:
            # If we cannot connect at all, add a general missing evidence.
            missing_evidence.append(f"Failed to connect to MongoDB: {exc}")

        return CollectedEvidence(
            evidence=evidence_list,
            missing_evidence=missing_evidence,
        )
