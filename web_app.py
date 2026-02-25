from flask import Flask, render_template, request, jsonify
import os
import sys
import signal
import atexit
import tempfile
from datetime import datetime
import io
from contextlib import redirect_stdout

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import Orchestrator

app = Flask(__name__)

orchestrator = Orchestrator()


_session_cleaned = False


def cleanup_session():
    global _session_cleaned
    if _session_cleaned:
        return
    _session_cleaned = True
    try:
        orchestrator.memory.end_current_session()
        print("\nSession ended and saved to long-term memory")
    except Exception as e:
        print(f"\nError saving session: {e}")


def signal_handler(sig, frame):
    print("\n\nShutting down web server...")
    cleanup_session()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_session)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        verbose = data.get('verbose', False)
        user_id = data.get('user_id', 'default')

        if not user_message.strip():
            return jsonify({'error': 'Empty message'})

        logs = []

        if verbose:
            captured_output = io.StringIO()
            with redirect_stdout(captured_output):
                result = orchestrator.run(
                    user_message, verbose=verbose, user_id=user_id
                )

            output_lines = captured_output.getvalue().split('\n')
            timestamp = datetime.now().strftime("%H:%M:%S")
            for line in output_lines:
                if line.strip():
                    logs.append(f"[{timestamp}] {line.strip()}")
        else:
            result = orchestrator.run(
                user_message, verbose=False, user_id=user_id
            )

        return jsonify({
            'response': result.result,
            'strategy': result.strategy_used,
            'success': result.success,
            'steps': result.steps_executed,
            'logs': logs,
            'error': result.error,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/upload', methods=['POST'])
def upload_document():
    """Upload a company document (PDF, DOCX, TXT)."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        user_id = request.form.get('user_id', 'default')

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Check file extension
        ext = os.path.splitext(file.filename)[1].lower().lstrip('.')
        if ext not in orchestrator.upload_manager.allowed_extensions:
            return jsonify({
                'error': (
                    f'Unsupported file type: .{ext}. '
                    f'Allowed: pdf, docx, txt'
                )
            }), 400

        # Save to temp file, then process
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=f'.{ext}'
        ) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            result = orchestrator.upload_manager.upload_document(
                file_path=tmp_path,
                original_filename=file.filename,
                user_id=user_id,
            )
            return jsonify(result)
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/documents', methods=['GET'])
def list_documents():
    """List all documents uploaded by a user."""
    try:
        user_id = request.args.get('user_id', 'default')
        documents = orchestrator.upload_manager.list_documents(user_id)
        chunk_count = orchestrator.upload_manager.get_user_doc_count(user_id)
        return jsonify({
            'documents': documents,
            'total_chunks': chunk_count,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Delete a specific uploaded document."""
    try:
        user_id = request.args.get('user_id', 'default')
        success = orchestrator.upload_manager.delete_document(user_id, doc_id)
        if success:
            return jsonify({'message': f'Document {doc_id} deleted'})
        else:
            return jsonify({'error': 'Document not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/evaluate', methods=['POST'])
def evaluate_compliance():
    """Trigger a compliance evaluation for a user's uploaded documents."""
    try:
        data = request.get_json()
        user_id = data.get('user_id', 'default')
        standards = data.get('standards', None)
        industry = data.get('industry', '')
        country = data.get('country', '')

        # Check if user has uploaded documents
        doc_count = orchestrator.upload_manager.get_user_doc_count(user_id)
        if doc_count == 0:
            return jsonify({
                'error': (
                    'No company documents found. Please upload your '
                    'company documents first before running an evaluation.'
                )
            }), 400

        report = orchestrator.evaluate_compliance(
            user_id=user_id,
            standards=standards,
            industry=industry,
            country=country,
        )

        return jsonify({
            'report': report,
            'standards_evaluated': standards or [
                'ISO 27001', 'SOC 2', 'GDPR', 'NIST CSF',
                'HIPAA', 'PCI DSS', 'COBIT',
            ],
            'industry': industry,
            'country': country,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/status')
def status():
    try:
        status_info = orchestrator.get_system_status()
        return jsonify(status_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/knowledge/status')
def knowledge_status():
    """Get knowledge base status."""
    try:
        kb_status = orchestrator.knowledge_base.get_status()
        return jsonify(kb_status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/reset', methods=['POST'])
def reset():
    try:
        orchestrator.reset_session()
        return jsonify({'message': 'Session reset successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting Compliance Agent Web Interface...")
    print("Access the interface at: http://localhost:5000")
    print("Press Ctrl+C to stop the server and save your session")
    app.run(debug=True, use_reloader=False, host='localhost', port=5000)