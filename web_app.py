import os
import sys
import signal
import atexit
import tempfile
import io
from datetime import datetime
from contextlib import redirect_stdout

from flask import Flask, render_template, request, jsonify

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import Orchestrator
from audit.audit_logger import AuditLogger
from evaluation.report_store import ReportStore

app = Flask(__name__)

# Thesis scope: fintech industry in Pakistan
INDUSTRY = "Fintech"
COUNTRY = "Pakistan"

orchestrator = Orchestrator()
audit = AuditLogger()
report_store = ReportStore()

audit.log(action="SYSTEM_START", details={"host": "localhost", "port": 5000})

_session_cleaned = False


def cleanup_session():
    """Save active session to long-term memory on shutdown."""
    global _session_cleaned
    if _session_cleaned:
        return
    _session_cleaned = True
    try:
        orchestrator.memory.end_current_session()
        audit.log(action="SESSION_END", user_id="system", details={"reason": "shutdown"})
        print("\nSession ended and saved to long-term memory")
    except Exception as e:
        print(f"\nError saving session: {e}")


def signal_handler(sig, frame):
    """Handle termination signals."""
    print("\n\nShutting down web server...")
    cleanup_session()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_session)


def _get_client_ip():
    """Extract client IP from the request, respecting proxy headers."""
    return request.headers.get("X-Forwarded-For", request.remote_addr) or ""


# ------------------------------------------------------------------
# Core routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main web interface."""
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    """Process a chat message through the compliance agent pipeline."""
    data = request.get_json() or {}
    try:
        user_message = data.get("message", "")
        verbose = data.get("verbose", False)
        user_id = data.get("user_id", "default")

        if not user_message.strip():
            return jsonify({"error": "Empty message"})

        logs = []

        if verbose:
            captured_output = io.StringIO()
            with redirect_stdout(captured_output):
                result = orchestrator.run(user_message, verbose=verbose, user_id=user_id)
            output_lines = captured_output.getvalue().split("\n")
            timestamp = datetime.now().strftime("%H:%M:%S")
            for line in output_lines:
                if line.strip():
                    logs.append(f"[{timestamp}] {line.strip()}")
        else:
            result = orchestrator.run(user_message, verbose=False, user_id=user_id)

        audit.log(
            action="CHAT_QUERY",
            user_id=user_id,
            resource_type="chat",
            details={
                "message_preview": user_message[:120],
                "strategy": result.strategy_used,
                "steps": result.steps_executed,
            },
            ip_address=_get_client_ip(),
            status="success" if result.success else "failure",
        )

        return jsonify({
            "response": result.result,
            "strategy": result.strategy_used,
            "success": result.success,
            "steps": result.steps_executed,
            "logs": logs,
            "error": result.error,
        })

    except Exception as e:
        audit.log(
            action="CHAT_QUERY",
            user_id=data.get("user_id", "default"),
            status="failure",
            details={"error": str(e)},
            ip_address=_get_client_ip(),
        )
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
def upload_document():
    """Upload a company document (PDF, DOCX, TXT) for compliance analysis."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        user_id = request.form.get("user_id", "default")

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
        if ext not in orchestrator.upload_manager.allowed_extensions:
            audit.log(
                action="DOCUMENT_UPLOAD",
                user_id=user_id,
                resource_type="document",
                details={"filename": file.filename, "rejected_ext": ext},
                ip_address=_get_client_ip(),
                status="failure",
            )
            return jsonify({
                "error": f"Unsupported file type: .{ext}. Allowed: pdf, docx, txt"
            }), 400

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            result = orchestrator.upload_manager.upload_document(
                file_path=tmp_path,
                original_filename=file.filename,
                user_id=user_id,
            )

            audit.log(
                action="DOCUMENT_UPLOAD",
                user_id=user_id,
                resource_type="document",
                resource_id=result.get("doc_id", ""),
                details={
                    "filename": file.filename,
                    "chunks": result.get("chunks", 0),
                    "characters": result.get("characters", 0),
                },
                ip_address=_get_client_ip(),
                status="success",
            )

            return jsonify(result)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/documents", methods=["GET"])
def list_documents():
    """List all documents uploaded by a user."""
    try:
        user_id = request.args.get("user_id", "default")
        documents = orchestrator.upload_manager.list_documents(user_id)
        chunk_count = orchestrator.upload_manager.get_user_doc_count(user_id)
        return jsonify({"documents": documents, "total_chunks": chunk_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/documents/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    """Delete a specific uploaded document."""
    try:
        user_id = request.args.get("user_id", "default")
        success = orchestrator.upload_manager.delete_document(user_id, doc_id)

        audit.log(
            action="DOCUMENT_DELETE",
            user_id=user_id,
            resource_type="document",
            resource_id=doc_id,
            ip_address=_get_client_ip(),
            status="success" if success else "failure",
        )

        if success:
            return jsonify({"message": f"Document {doc_id} deleted"})
        else:
            return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Evaluation routes
# ------------------------------------------------------------------

@app.route("/evaluate", methods=["POST"])
def evaluate_compliance():
    """Run a compliance evaluation against the user's uploaded documents."""
    data = request.get_json() or {}
    try:
        user_id = data.get("user_id", "default")
        standards = data.get("standards", None)
        industry = INDUSTRY
        country = COUNTRY

        doc_count = orchestrator.upload_manager.get_user_doc_count(user_id)
        if doc_count == 0:
            return jsonify({
                "warning": (
                    "No company documents found. Please upload your "
                    "company documents first before running an evaluation."
                )
            }), 200

        logs = []
        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            report = orchestrator.evaluate_compliance(
                user_id=user_id,
                standards=standards,
                industry=industry,
                country=country,
                verbose=True,
            )
        output_lines = captured_output.getvalue().split("\n")
        timestamp = datetime.now().strftime("%H:%M:%S")
        for line in output_lines:
            if line.strip():
                logs.append(f"[{timestamp}] {line.strip()}")

        # Persist the report
        evaluated_standards = standards or [
            "ISO 27001", "SOC 2", "GDPR", "NIST CSF", "PCI DSS",
            "SBP Regulations", "FATF", "SECP Guidelines", "Pakistan AML/CFT",
        ]
        report_meta = report_store.save_report(
            user_id=user_id,
            report_text=report,
            standards=evaluated_standards,
            industry=industry,
            country=country,
        )

        audit.log(
            action="EVALUATION_RUN",
            user_id=user_id,
            resource_type="evaluation",
            resource_id=report_meta.get("report_id", ""),
            details={
                "standards": evaluated_standards,
                "industry": industry,
                "country": country,
            },
            ip_address=_get_client_ip(),
            status="success",
        )

        return jsonify({
            "report": report,
            "report_id": report_meta.get("report_id"),
            "standards_evaluated": evaluated_standards,
            "industry": industry,
            "country": country,
            "logs": logs,
        })

    except Exception as e:
        audit.log(
            action="EVALUATION_RUN",
            user_id=data.get("user_id", "default"),
            status="failure",
            details={"error": str(e)},
            ip_address=_get_client_ip(),
        )
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Report history routes
# ------------------------------------------------------------------

@app.route("/reports", methods=["GET"])
def list_reports():
    """List saved evaluation reports for a user."""
    try:
        user_id = request.args.get("user_id", "default")
        reports = report_store.list_reports(user_id)
        return jsonify({"reports": reports})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reports/<report_id>", methods=["GET"])
def get_report(report_id):
    """Retrieve a specific evaluation report."""
    try:
        user_id = request.args.get("user_id", "default")
        report = report_store.get_report(user_id, report_id)
        if report:
            return jsonify(report)
        return jsonify({"error": "Report not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reports/<report_id>", methods=["DELETE"])
def delete_report(report_id):
    """Delete a specific evaluation report."""
    try:
        user_id = request.args.get("user_id", "default")
        success = report_store.delete_report(user_id, report_id)

        audit.log(
            action="REPORT_DELETE",
            user_id=user_id,
            resource_type="report",
            resource_id=report_id,
            ip_address=_get_client_ip(),
            status="success" if success else "failure",
        )

        if success:
            return jsonify({"message": f"Report {report_id} deleted"})
        return jsonify({"error": "Report not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reports/<report_id>/download", methods=["GET"])
def download_report(report_id):
    """Download a report as markdown text."""
    try:
        user_id = request.args.get("user_id", "default")
        report = report_store.get_report(user_id, report_id)
        if not report:
            return jsonify({"error": "Report not found"}), 404

        audit.log(
            action="REPORT_DOWNLOAD",
            user_id=user_id,
            resource_type="report",
            resource_id=report_id,
            ip_address=_get_client_ip(),
        )

        return app.response_class(
            response=report.get("report_text", ""),
            status=200,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=report_{report_id}.md"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Audit trail routes
# ------------------------------------------------------------------

@app.route("/audit/logs", methods=["GET"])
def audit_logs():
    """Query audit trail with optional filters."""
    try:
        logs = audit.query(
            user_id=request.args.get("user_id"),
            action=request.args.get("action"),
            resource_type=request.args.get("resource_type"),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
            status=request.args.get("status"),
            limit=int(request.args.get("limit", 100)),
            offset=int(request.args.get("offset", 0)),
        )
        return jsonify({"logs": logs, "count": len(logs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/audit/summary", methods=["GET"])
def audit_summary():
    """Return audit trail aggregate statistics."""
    try:
        summary = audit.get_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/audit/export", methods=["GET"])
def audit_export():
    """Export audit trail as CSV."""
    try:
        # Use a unique temp file so concurrent exports do not clobber each other.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tmp:
            export_path = tmp.name
        try:
            audit.export_csv(export_path)
            with open(export_path, "r", encoding="utf-8") as f:
                csv_content = f.read()
        finally:
            if os.path.exists(export_path):
                os.remove(export_path)

        return app.response_class(
            response=csv_content,
            status=200,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# System status routes
# ------------------------------------------------------------------

@app.route("/status")
def status():
    """Return system component status."""
    try:
        status_info = orchestrator.get_system_status()
        return jsonify(status_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/status")
def knowledge_status():
    """Return knowledge base status including loaded standards."""
    try:
        kb_status = orchestrator.knowledge_base.get_status()
        return jsonify(kb_status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/standards")
def knowledge_standards():
    """List all loaded regulatory standards with their metadata."""
    try:
        standards = orchestrator.knowledge_base.list_standards()
        return jsonify({"standards": standards})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/standards/<filename>/download")
def download_knowledge_standard(filename):
    """Download a regulatory knowledge document as a Markdown file."""
    try:
        # Validate against the known standards list to prevent path traversal
        known = {s["filename"] for s in orchestrator.knowledge_base.list_standards()}
        if filename not in known:
            return jsonify({"error": "Standard not found"}), 404

        knowledge_path = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge_data")
        filepath = os.path.join(knowledge_path, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        audit.log(
            action="KNOWLEDGE_DOWNLOAD",
            user_id=request.args.get("user_id", "anonymous"),
            resource_type="knowledge",
            resource_id=filename,
            ip_address=_get_client_ip(),
            status="success",
        )

        return app.response_class(
            response=content,
            status=200,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reset", methods=["POST"])
def reset():
    """Reset the current session memory."""
    try:
        user_id = (request.get_json(silent=True) or {}).get("user_id", "default")
        orchestrator.reset_session()

        audit.log(
            action="SESSION_RESET",
            user_id=user_id,
            ip_address=_get_client_ip(),
        )

        return jsonify({"message": "Session reset successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Compliance Agent Web Interface...")
    print("Access the interface at: http://localhost:5000")
    print("Press Ctrl+C to stop the server and save your session")
    app.run(debug=False, use_reloader=False, host="localhost", port=5000)