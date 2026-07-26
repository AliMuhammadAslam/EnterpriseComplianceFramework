import os
import sys
import signal
import atexit
import tempfile
import io
from functools import wraps
from datetime import datetime
from contextlib import redirect_stdout

from flask import (
    Flask, render_template, request, jsonify, session, redirect, url_for
)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import Orchestrator
from audit.audit_logger import AuditLogger
from evaluation.report_store import ReportStore
from auth.user_store import UserStore

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# Thesis scope: fintech industry in Pakistan
INDUSTRY = "Fintech"
COUNTRY = "Pakistan"

# Caps report generation within the LLM's token budget; the UI enforces this
# too, this is the server-side safety net for direct API calls.
MAX_STANDARDS_PER_EVALUATION = 10

orchestrator = Orchestrator()
audit = AuditLogger()
report_store = ReportStore()
user_store = UserStore()

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


@app.after_request
def add_no_cache_headers(response):
    """Stop the browser caching signed-in pages.

    Without this the back button can serve a logged-in page from cache after
    the user has signed out, showing the previous user's details.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def login_required(f):
    """Reject unauthenticated data requests with a 401."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper


def _current_user_id():
    """The logged-in user's data key, taken from the session, never the client."""
    return session.get("user_id", "")


# ------------------------------------------------------------------
# Authentication routes
# ------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Show the login page and authenticate a fixed account."""
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("login.html")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    profile = user_store.verify(username, password)

    if not profile:
        audit.log(
            action="LOGIN",
            user_id=(username or "unknown").strip().lower(),
            status="failure",
            details={"reason": "invalid credentials"},
            ip_address=_get_client_ip(),
        )
        return render_template(
            "login.html", error="Invalid username or password"
        ), 401

    session.clear()
    session["user_id"] = profile["user_id"]
    session["username"] = profile["username"]
    session["name"] = profile["name"]
    session["role"] = profile["role"]
    audit.log(
        action="LOGIN",
        user_id=profile["user_id"],
        status="success",
        ip_address=_get_client_ip(),
    )
    return redirect(url_for("index"))


@app.route("/logout", methods=["POST"])
def logout():
    """Clear the session and return to the login page."""
    uid = session.get("user_id", "")
    session.clear()
    if uid:
        audit.log(action="LOGOUT", user_id=uid, ip_address=_get_client_ip())
    return jsonify({"message": "Logged out"})


# ------------------------------------------------------------------
# Core routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main web interface, or the login page if not signed in."""
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template(
        "index.html",
        user_id=session["user_id"],
        user_name=session.get("name", ""),
        user_role=session.get("role", ""),
        username=session.get("username", ""),
    )


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    """Process a chat message through the compliance agent pipeline."""
    data = request.get_json() or {}
    try:
        user_message = data.get("message", "")
        verbose = data.get("verbose", False)
        user_id = _current_user_id()

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
            user_id=_current_user_id(),
            status="failure",
            details={"error": str(e)},
            ip_address=_get_client_ip(),
        )
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
@login_required
def upload_document():
    """Upload a company document (PDF, DOCX, TXT) for compliance analysis."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        user_id = _current_user_id()

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
@login_required
def list_documents():
    """List all documents uploaded by a user."""
    try:
        user_id = _current_user_id()
        documents = orchestrator.upload_manager.list_documents(user_id)
        chunk_count = orchestrator.upload_manager.get_user_doc_count(user_id)
        return jsonify({"documents": documents, "total_chunks": chunk_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/documents/<doc_id>", methods=["DELETE"])
@login_required
def delete_document(doc_id):
    """Delete a specific uploaded document."""
    try:
        user_id = _current_user_id()
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
@login_required
def evaluate_compliance():
    """Run a compliance evaluation against the user's uploaded documents."""
    data = request.get_json() or {}
    try:
        user_id = _current_user_id()
        standards = data.get("standards", None)
        doc_ids = data.get("doc_ids", None) or None
        industry = INDUSTRY
        country = COUNTRY

        if standards and len(standards) > MAX_STANDARDS_PER_EVALUATION:
            return jsonify({
                "error": (
                    f"Too many standards selected ({len(standards)}). "
                    f"Maximum {MAX_STANDARDS_PER_EVALUATION} standards per evaluation."
                )
            }), 400

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
                doc_ids=doc_ids,
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
            user_id=_current_user_id(),
            status="failure",
            details={"error": str(e)},
            ip_address=_get_client_ip(),
        )
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Report history routes
# ------------------------------------------------------------------

@app.route("/reports", methods=["GET"])
@login_required
def list_reports():
    """List saved evaluation reports for a user."""
    try:
        user_id = _current_user_id()
        reports = report_store.list_reports(user_id)
        return jsonify({"reports": reports})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reports/<report_id>", methods=["GET"])
@login_required
def get_report(report_id):
    """Retrieve a specific evaluation report."""
    try:
        user_id = _current_user_id()
        report = report_store.get_report(user_id, report_id)
        if report:
            return jsonify(report)
        return jsonify({"error": "Report not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reports/<report_id>", methods=["DELETE"])
@login_required
def delete_report(report_id):
    """Delete a specific evaluation report."""
    try:
        user_id = _current_user_id()
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
@login_required
def download_report(report_id):
    """Download a report as markdown text."""
    try:
        user_id = _current_user_id()
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
@login_required
def audit_logs():
    """Query the current user's audit trail with optional filters."""
    try:
        logs = audit.query(
            user_id=_current_user_id(),
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
@login_required
def audit_summary():
    """Return audit trail aggregate statistics."""
    try:
        summary = audit.get_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/audit/export", methods=["GET"])
@login_required
def audit_export():
    """Export audit trail as CSV."""
    try:
        # Use a unique temp file so concurrent exports do not clobber each other.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as tmp:
            export_path = tmp.name
        try:
            audit.export_csv(export_path, user_id=_current_user_id())
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
@login_required
def status():
    """Return system component status."""
    try:
        status_info = orchestrator.get_system_status()
        return jsonify(status_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/status")
@login_required
def knowledge_status():
    """Return knowledge base status including loaded standards."""
    try:
        kb_status = orchestrator.knowledge_base.get_status()
        return jsonify(kb_status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/standards")
@login_required
def knowledge_standards():
    """List all loaded regulatory standards with their metadata."""
    try:
        standards = orchestrator.knowledge_base.list_standards()
        return jsonify({"standards": standards})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/knowledge/standards/<filename>/download")
@login_required
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
            user_id=_current_user_id(),
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
@login_required
def reset():
    """Reset the current session memory."""
    try:
        user_id = _current_user_id()
        orchestrator.reset_session(user_id=user_id)

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