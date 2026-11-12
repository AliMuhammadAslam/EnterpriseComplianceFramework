"""Per-thread capture of printed output.

contextlib.redirect_stdout swaps sys.stdout for the whole process. Under a
threaded server two overlapping requests then capture each other's output, so
one user's verbose log can show another user's queries. This routes writes to
a buffer owned by the capturing thread and leaves every other thread's output
going to the real stream.
"""

import io
import sys
import threading
from contextlib import contextmanager
from datetime import datetime

_local = threading.local()


class _ThreadRoutedStream:
    """Stands in for sys.stdout and sends each write to the right place."""

    def __init__(self, fallback):
        self._fallback = fallback

    def _target(self):
        buffer = getattr(_local, "buffer", None)
        return buffer if buffer is not None else self._fallback

    def write(self, text):
        return self._target().write(text)

    def flush(self):
        return self._target().flush()

    def __getattr__(self, name):
        # isatty, encoding, fileno and the rest come from the real stream.
        return getattr(self._fallback, name)


class _TimedBuffer(io.StringIO):
    """A StringIO that also records when each line began.

    The routes used to stamp every captured line with one time taken after the
    request had finished, so a long run showed the same second on every line.
    Recording the time as each line starts gives the real time of each step.
    getvalue() is unchanged.
    """

    def __init__(self):
        super().__init__()
        self._lines = []        # [started_at, text] per line, in order
        self._line_open = False  # True while the last line has no newline yet

    def write(self, text):
        written = super().write(text)
        pieces = text.split("\n")
        for i, piece in enumerate(pieces):
            ends_line = i < len(pieces) - 1
            if not piece and not ends_line:
                continue  # nothing after the final newline
            if self._line_open:
                self._lines[-1][1] += piece
            else:
                self._lines.append([datetime.now(), piece])
            self._line_open = not ends_line
        return written

    def timed_lines(self):
        """Return (time the line began, stripped text) for each non-blank line."""
        return [(started, text.strip()) for started, text in self._lines if text.strip()]


_install_lock = threading.Lock()


def _install():
    """Put the routing stream in place once, wrapping whatever stdout is now."""
    with _install_lock:
        if not isinstance(sys.stdout, _ThreadRoutedStream):
            sys.stdout = _ThreadRoutedStream(sys.stdout)


@contextmanager
def capture_output():
    """Collect what this thread prints inside the block.

    Yields a StringIO; its timed_lines() gives each line with the time it was
    written.
    """
    _install()
    previous = getattr(_local, "buffer", None)
    buffer = _TimedBuffer()
    _local.buffer = buffer
    try:
        yield buffer
    finally:
        _local.buffer = previous
