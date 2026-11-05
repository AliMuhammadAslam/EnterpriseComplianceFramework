import os
import re
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance

# Report ids are generated as the first 8 hex characters of a UUID. Anything
# else is rejected before it reaches a path: on Windows a backslash in the id
# is a path separator, so "..\..\users" would resolve outside the reports dir.
_REPORT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ReportStore:
    """Saves and retrieves compliance evaluation reports stored per user."""

    def __init__(self, reports_dir: str = None):
        self.reports_dir = reports_dir or os.getenv("REPORTS_DIR", "./reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self.logger = logger_instance.get_logger("report_store")

    def save_report(
        self,
        user_id: str,
        report_text: str,
        standards: List[str],
        industry: str = "",
        country: str = "",
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Save an evaluation report and return its metadata.

        trace_id links the report to the evidence trace it was built from.
        """
        report_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        record = {
            "report_id": report_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "standards": standards,
            "industry": industry,
            "country": country,
            "trace_id": trace_id,
            "report_text": report_text,
        }

        user_dir = os.path.join(self.reports_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)

        filepath = os.path.join(user_dir, f"{report_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        self.logger.info(f"Saved report {report_id} for user {user_id}")

        return {
            "report_id": report_id,
            "timestamp": timestamp,
            "standards": standards,
            "industry": industry,
            "country": country,
        }

    def list_reports(self, user_id: str) -> List[Dict[str, Any]]:
        """Return metadata for all saved reports, newest first."""
        user_dir = os.path.join(self.reports_dir, user_id)
        if not os.path.exists(user_dir):
            return []

        reports = []
        for filename in os.listdir(user_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(user_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        record = json.load(f)
                    reports.append({
                        "report_id": record["report_id"],
                        "timestamp": record["timestamp"],
                        "standards": record.get("standards", []),
                        "industry": record.get("industry", ""),
                        "country": record.get("country", ""),
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    self.logger.warning(f"Skipping corrupt report file {filename}: {e}")

        reports.sort(key=lambda r: r["timestamp"], reverse=True)
        return reports

    def _report_path(self, user_id: str, report_id: str) -> Optional[str]:
        """Path of a report file, or None if the id could point anywhere else."""
        if not isinstance(report_id, str) or not _REPORT_ID.match(report_id):
            return None
        user_dir = os.path.realpath(os.path.join(self.reports_dir, user_id))
        filepath = os.path.realpath(os.path.join(user_dir, f"{report_id}.json"))
        if os.path.dirname(filepath) != user_dir:
            return None
        return filepath

    def get_report(self, user_id: str, report_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific report including full text, or None if not found."""
        filepath = self._report_path(user_id, report_id)
        if not filepath or not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete_report(self, user_id: str, report_id: str) -> bool:
        """Delete a report. Returns True if found and deleted."""
        filepath = self._report_path(user_id, report_id)
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            self.logger.info(f"Deleted report {report_id} for user {user_id}")
            return True
        return False
