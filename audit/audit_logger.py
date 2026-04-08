import json
import csv
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from utils.logger import logger_instance


class AuditEntry(BaseModel):
    """Single audit log entry for tracking system actions."""
    event_id: str
    timestamp: str
    user_id: str
    action: str
    resource_type: str = ""
    resource_id: str = ""
    details: Dict[str, Any] = {}
    ip_address: str = ""
    status: str = "success"


# Supported audit action types
AUDIT_ACTIONS = {
    "CHAT_QUERY": "User sent a chat query",
    "DOCUMENT_UPLOAD": "Document uploaded to the system",
    "DOCUMENT_DELETE": "Document deleted from the system",
    "EVALUATION_RUN": "Compliance evaluation executed",
    "SESSION_RESET": "User session reset",
    "SESSION_END": "User session ended",
    "KNOWLEDGE_INGEST": "Knowledge base ingested or re-ingested",
    "SYSTEM_START": "Application started",
    "REPORT_DOWNLOAD": "Evaluation report downloaded",
    "KNOWLEDGE_QUERY": "Knowledge base queried",
}


class AuditLogger:
    """Persistent audit logger using JSON Lines format.

    Writes each audit event as a single JSON line to `audit_log.jsonl`.
    Supports querying, filtering, and CSV export for compliance reporting.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_dir: str = None):
        if self._initialized:
            return
        self.log_dir = log_dir or os.getenv("AUDIT_LOG_DIR", "./audit_logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "audit_log.jsonl")
        self.logger = logger_instance.get_logger("audit")
        self._initialized = True
        self.logger.info(f"AuditLogger initialized, log file: {self.log_file}")

    def log(
        self,
        action: str,
        user_id: str = "system",
        resource_type: str = "",
        resource_id: str = "",
        details: Dict[str, Any] = None,
        ip_address: str = "",
        status: str = "success",
    ) -> AuditEntry:
        """Record an audit event.

        Args:
            action: Action type from AUDIT_ACTIONS.
            user_id: Identifier of the user performing the action.
            resource_type: Type of resource affected (e.g., 'document', 'session').
            resource_id: Identifier of the affected resource.
            details: Additional context about the event.
            ip_address: Client IP address if available.
            status: Outcome of the action ('success' or 'failure').

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            event_id=str(uuid.uuid4())[:12],
            timestamp=datetime.now().isoformat(),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            status=status,
        )

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        except Exception as e:
            self.logger.error(f"Failed to write audit entry: {e}")

        return entry

    def query(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query audit logs with optional filtering.

        Args:
            user_id: Filter by user.
            action: Filter by action type.
            resource_type: Filter by resource type.
            start_date: ISO datetime string for range start (inclusive).
            end_date: ISO datetime string for range end (inclusive).
            status: Filter by status ('success' or 'failure').
            limit: Maximum entries to return.
            offset: Number of entries to skip.

        Returns:
            List of matching audit entries as dictionaries.
        """
        entries = self._read_all_entries()

        # Apply filters
        if user_id:
            entries = [e for e in entries if e["user_id"] == user_id]
        if action:
            entries = [e for e in entries if e["action"] == action]
        if resource_type:
            entries = [e for e in entries if e["resource_type"] == resource_type]
        if status:
            entries = [e for e in entries if e["status"] == status]
        if start_date:
            entries = [e for e in entries if e["timestamp"] >= start_date]
        if end_date:
            entries = [e for e in entries if e["timestamp"] <= end_date]

        # Sort newest first, apply pagination
        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        return entries[offset:offset + limit]

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregate statistics from the audit log."""
        entries = self._read_all_entries()
        action_counts = {}
        user_counts = {}
        for entry in entries:
            action_counts[entry["action"]] = action_counts.get(entry["action"], 0) + 1
            user_counts[entry["user_id"]] = user_counts.get(entry["user_id"], 0) + 1

        return {
            "total_events": len(entries),
            "actions": action_counts,
            "users": user_counts,
            "earliest": entries[-1]["timestamp"] if entries else None,
            "latest": entries[0]["timestamp"] if entries else None,
        }

    def export_csv(self, filepath: str, **filters) -> str:
        """Export filtered audit entries to a CSV file.

        Args:
            filepath: Output CSV path.
            **filters: Keyword arguments passed to query().

        Returns:
            Path to the exported CSV file.
        """
        entries = self.query(**filters, limit=10000)
        if not entries:
            return filepath

        fieldnames = [
            "event_id", "timestamp", "user_id", "action",
            "resource_type", "resource_id", "status", "ip_address", "details",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in entries:
                row = {k: entry.get(k, "") for k in fieldnames}
                row["details"] = json.dumps(entry.get("details", {}))
                writer.writerow(row)

        self.logger.info(f"Exported {len(entries)} audit entries to {filepath}")
        return filepath

    def _read_all_entries(self) -> List[Dict[str, Any]]:
        """Read all entries from the audit log file."""
        entries = []
        if not os.path.exists(self.log_file):
            return entries

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            self.logger.error(f"Failed to read audit log: {e}")

        # Sort newest first
        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries
