import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SnapshotPersistence:
    def __init__(self, db_path: str | Path = "data/audit_snapshots.db") -> None:
        self.db_path = Path(db_path)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except Exception:
            logger.exception("Failed to initialize audit snapshot database at %s", self.db_path)

    def _init_db(self):
        """Initialize SQLite schema for audit/replay only."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Table: analysis_requests (Contract A data)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analysis_requests (
                    analysis_id TEXT PRIMARY KEY,
                    request_timestamp DATETIME NOT NULL,
                    contract_a_data JSON NOT NULL
                )
            """)

            # Table: evidence_snapshots (Contract B evidence array)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evidence_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id TEXT NOT NULL,
                    evidence_data JSON NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(analysis_id) REFERENCES analysis_requests(analysis_id)
                )
            """)

            # Table: deterministic_findings (Contract B findings array)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deterministic_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id TEXT NOT NULL,
                    findings_data JSON NOT NULL,
                    rule_version TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(analysis_id) REFERENCES analysis_requests(analysis_id)
                )
            """)

            # Table: rule_versions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rule_versions (
                    version_id TEXT PRIMARY KEY,
                    description TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()

    def save_snapshot(
        self,
        analysis_id: str,
        contract_a_data: dict[str, Any],
        evidence: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        rule_version: str,
    ) -> bool:
        """
        Save analysis snapshot before sending to AI.
        Non-blocking: failures are logged but do not raise exceptions to pipeline.
        """
        try:
            now = datetime.now(UTC).isoformat()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Insert Request
                cursor.execute(
                    "INSERT OR REPLACE INTO analysis_requests "
                    "(analysis_id, request_timestamp, contract_a_data) VALUES (?, ?, ?)",
                    (analysis_id, now, json.dumps(contract_a_data)),
                )

                # Insert Evidence
                cursor.execute(
                    "INSERT INTO evidence_snapshots (analysis_id, evidence_data) VALUES (?, ?)",
                    (analysis_id, json.dumps(evidence)),
                )

                # Insert Findings
                cursor.execute(
                    "INSERT INTO deterministic_findings "
                    "(analysis_id, findings_data, rule_version) VALUES (?, ?, ?)",
                    (analysis_id, json.dumps(findings), rule_version),
                )

                # Ensure rule version exists
                cursor.execute(
                    "INSERT OR IGNORE INTO rule_versions (version_id, description) VALUES (?, ?)",
                    (rule_version, f"Rule set {rule_version}"),
                )

                conn.commit()
                logger.info(f"Snapshot saved for analysis_id: {analysis_id}")
                return True

        except Exception as e:
            # Success Criteria: Proper error handling for DB failures (non-blocking)
            logger.error(f"Failed to save snapshot for {analysis_id}: {e}")
            return False

    def get_snapshot(self, analysis_id: str) -> dict[str, Any] | None:
        """Retrieve snapshot for audit/replay. Not used in live analysis."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT * FROM analysis_requests WHERE analysis_id = ?", (analysis_id,)
                )
                req_row = cursor.fetchone()
                if not req_row:
                    return None

                cursor.execute(
                    "SELECT evidence_data FROM evidence_snapshots "
                    "WHERE analysis_id = ? ORDER BY id DESC LIMIT 1",
                    (analysis_id,),
                )
                ev_row = cursor.fetchone()

                cursor.execute(
                    "SELECT findings_data, rule_version FROM deterministic_findings "
                    "WHERE analysis_id = ? ORDER BY id DESC LIMIT 1",
                    (analysis_id,),
                )
                fd_row = cursor.fetchone()

                return {
                    "analysis_id": req_row["analysis_id"],
                    "request_timestamp": req_row["request_timestamp"],
                    "contract_a": json.loads(req_row["contract_a_data"]),
                    "evidence": json.loads(ev_row["evidence_data"]) if ev_row else [],
                    "findings": json.loads(fd_row["findings_data"]) if fd_row else [],
                    "rule_version": fd_row["rule_version"] if fd_row else None,
                }
        except Exception as e:
            logger.error(f"Error retrieving snapshot for {analysis_id}: {e}")
            return None

    def verify_schema(self) -> bool:
        """Verify that the audit tables and their required columns exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                required_columns = {
                    "analysis_requests": {
                        "analysis_id",
                        "request_timestamp",
                        "contract_a_data",
                    },
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
                for table, expected_columns in required_columns.items():
                    cursor.execute(f"PRAGMA table_info({table})")
                    actual_columns = {row[1] for row in cursor.fetchall()}
                    if not expected_columns.issubset(actual_columns):
                        return False
                return True
        except Exception:
            return False
