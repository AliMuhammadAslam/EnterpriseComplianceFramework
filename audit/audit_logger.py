import json
import csv
import os
import uuid
import hashlib
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from utils.logger import logger_instance

# First link in the chain, used as prev_hash for the earliest hashed entry.
GENESIS_HASH = "0" * 64


class AuditEntry(BaseModel):
    """Single audit log entry for tracking system actions.

    Entries are hash chained, so editing or deleting one breaks every link
    after it. This gives tamper evidence, not tamper prevention: anyone with
    write access to the file can still rebuild the whole chain, so a real
    deployment needs an append-only or replicated store as well.
    """
    event_id: str
    timestamp: str
    user_id: str
    action: str
    resource_type: str = ""
    resource_id: str = ""
    details: Dict[str, Any] = {}
    ip_address: str = ""
    status: str = "success"
    prev_hash: str = ""
    entry_hash: str = ""


def compute_entry_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 over the canonical form of an entry, excluding its own hash."""
    body = {k: v for k, v in payload.items() if k != "entry_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        # Serialises appends so concurrent requests in the same process cannot
        # interleave partial lines. This does not protect against multiple
        # worker processes, which need an external collector instead.
        self._write_lock = threading.Lock()
        self._last_hash = self._load_last_hash()
        self._initialized = True
        self.logger.info(f"AuditLogger initialized, log file: {self.log_file}")

    @classmethod
    def _reset_singleton(cls):
        """Drop the cached instance. Used by tests to isolate log directories."""
        cls._instance = None

    def _load_last_hash(self) -> str:
        """Return the hash of the final chained entry, or the genesis value.

        Entries written before hash chaining existed carry no hash, so the
        chain simply begins at the first entry that has one.
        """
        last = GENESIS_HASH
        if not os.path.exists(self.log_file):
            return last
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("entry_hash"):
                        last = record["entry_hash"]
        except Exception as e:
            self.logger.error(f"Failed to read audit chain head: {e}")
        return last

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
        """Append an audit event to the log file, chained to the previous entry."""
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

        # Hash assignment and the append happen under one lock so that two
        # concurrent writers cannot both chain from the same predecessor.
        with self._write_lock:
            entry.prev_hash = self._last_hash
            entry.entry_hash = compute_entry_hash(entry.model_dump())
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(entry.model_dump_json() + "\n")
                self._last_hash = entry.entry_hash
            except Exception as e:
                self.logger.error(f"Failed to write audit entry: {e}")

        return entry

    def verify_chain(self) -> Dict[str, Any]:
        """Recompute the hash chain and report whether the log is intact.

        Entries predating hash chaining are counted separately rather than
        treated as failures, since they were never chained in the first place.
        """
        entries = self._read_raw_entries()
        unchained = 0
        verified = 0
        expected_prev = GENESIS_HASH
        problems = []

        for position, record in enumerate(entries):
            stored = record.get("entry_hash")
            if not stored:
                unchained += 1
                continue

            recomputed = compute_entry_hash(record)
            if recomputed != stored:
                problems.append({
                    "position": position,
                    "event_id": record.get("event_id"),
                    "problem": "contents do not match the recorded hash",
                })
            elif record.get("prev_hash") != expected_prev:
                problems.append({
                    "position": position,
                    "event_id": record.get("event_id"),
                    "problem": "predecessor link is broken, an entry was altered or removed",
                })
            else:
                verified += 1

            expected_prev = stored

        return {
            "intact": not problems,
            "total_entries": len(entries),
            "verified": verified,
            "unchained_legacy_entries": unchained,
            "problems": problems,
        }

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
        """Return audit entries matching the given filters, newest first."""
        entries = self._read_all_entries()

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
        """Export filtered audit entries to a CSV file and return the path."""
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

    def _read_raw_entries(self) -> List[Dict[str, Any]]:
        """Read entries in the order they were written.

        Chain verification depends on write order, so this must not be sorted.
        """
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

        return entries

    def _read_all_entries(self) -> List[Dict[str, Any]]:
        """Read all entries from the audit log file, newest first."""
        entries = self._read_raw_entries()
        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries
