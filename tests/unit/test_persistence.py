import sqlite3

import pytest

from services.analysis_service.app.storage.persistence import SnapshotPersistence


@pytest.fixture
def persistence(tmp_path):
    return SnapshotPersistence(db_path=tmp_path / "audit.db")


def test_save_and_retrieve_snapshot(persistence):
    analysis_id = "test-123"
    contract_a = {"database": "prod-db", "environment": "production"}
    evidence = [{"type": "query_log", "content": "SELECT 1"}]
    findings = [{"rule": "R001", "severity": "HIGH", "message": "Slow query detected"}]
    rule_version = "v1.0.2"

    # Test insertion
    success = persistence.save_snapshot(
        analysis_id=analysis_id,
        contract_a_data=contract_a,
        evidence=evidence,
        findings=findings,
        rule_version=rule_version,
    )
    assert success is True

    # Test retrieval
    snapshot = persistence.get_snapshot(analysis_id)
    assert snapshot is not None
    assert snapshot["analysis_id"] == analysis_id
    assert snapshot["contract_a"] == contract_a
    assert snapshot["evidence"] == evidence
    assert snapshot["findings"] == findings
    assert snapshot["rule_version"] == rule_version


def test_schema_correctness(persistence):
    assert persistence.verify_schema() is True
    with sqlite3.connect(persistence.db_path) as connection:
        expected_columns = {
            "analysis_requests": {"analysis_id", "request_timestamp", "contract_a_data"},
            "evidence_snapshots": {"id", "analysis_id", "evidence_data", "created_at"},
            "deterministic_findings": {
                "id",
                "analysis_id",
                "findings_data",
                "rule_version",
                "created_at",
            },
            "rule_versions": {"version_id", "description", "created_at"},
        }
        for table, columns in expected_columns.items():
            actual_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert columns.issubset(actual_columns)


def test_non_blocking_on_invalid_data(persistence):
    # Passing non-serializable data should fail gracefully without raising exception
    class Unserializable:
        pass

    result = persistence.save_snapshot(
        analysis_id="fail-test",
        contract_a_data={"obj": Unserializable()},
        evidence=[],
        findings=[],
        rule_version="v1",
    )
    assert result is False  # Should return False instead of crashing


def test_database_write_failure_is_non_blocking(persistence, monkeypatch):
    def fail_connect(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database failure")

    monkeypatch.setattr(
        "services.analysis_service.app.storage.persistence.sqlite3.connect", fail_connect
    )

    assert persistence.save_snapshot("db-failure", {}, [], [], "v1") is False


def test_database_initialization_failure_is_non_blocking(tmp_path):
    non_directory_parent = tmp_path / "not-a-directory"
    non_directory_parent.write_text("block directory creation", encoding="utf-8")

    persistence = SnapshotPersistence(non_directory_parent / "audit.db")

    assert persistence.verify_schema() is False
    assert persistence.save_snapshot("init-failure", {}, [], [], "v1") is False


def test_rule_version_is_recorded(persistence):
    persistence.save_snapshot("read-only-test", {}, [], [], "v1")
    with sqlite3.connect(persistence.db_path) as connection:
        assert connection.execute(
            "SELECT version_id FROM rule_versions WHERE version_id = ?", ("v1",)
        ).fetchone() == ("v1",)
