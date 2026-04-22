import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance


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
    ) -> Dict[str, Any]:
        """Save an evaluation report and return its metadata."""
        report_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        record = {
            "report_id": report_id,
            "user_id": user_id,
            "timestamp": timestamp,
            "standards": standards,
            "industry": industry,
            "country": country,
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

    def get_report(self, user_id: str, report_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific report including full text, or None if not found."""
        filepath = os.path.join(self.reports_dir, user_id, f"{report_id}.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete_report(self, user_id: str, report_id: str) -> bool:
        """Delete a report. Returns True if found and deleted."""
        filepath = os.path.join(self.reports_dir, user_id, f"{report_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            self.logger.info(f"Deleted report {report_id} for user {user_id}")
            return True
        return False
