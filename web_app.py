from flask import Flask, render_template, request, jsonify
import os
import sys
import signal
import atexit
from datetime import datetime
import io
from contextlib import redirect_stdout

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import Orchestrator

app = Flask(__name__)

orchestrator = Orchestrator()


def cleanup_session():
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

        if not user_message.strip():
            return jsonify({'error': 'Empty message'})

        logs = []

        if verbose:
            captured_output = io.StringIO()
            with redirect_stdout(captured_output):
                result = orchestrator.run(user_message, verbose=verbose)

            output_lines = captured_output.getvalue().split('\n')
            timestamp = datetime.now().strftime("%H:%M:%S")
            for line in output_lines:
                if line.strip():
                    logs.append(f"[{timestamp}] {line.strip()}")
        else:
            result = orchestrator.run(user_message, verbose=False)
        
        return jsonify({
            'response': result.result,
            'strategy': result.strategy_used,
            'success': result.success,
            'steps': result.steps_executed,
            'logs': logs,
            'error': result.error
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


@app.route('/reset', methods=['POST'])
def reset():
    try:
        orchestrator.reset_session()
        return jsonify({'message': 'Session reset successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting AI Agent Web Interface...")
    print("Access the interface at: http://localhost:5000")
    print("Press Ctrl+C to stop the server and save your session")
    app.run(debug=True, host='localhost', port=5000)