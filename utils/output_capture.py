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


_install_lock = threading.Lock()


def _install():
    """Put the routing stream in place once, wrapping whatever stdout is now."""
    with _install_lock:
        if not isinstance(sys.stdout, _ThreadRoutedStream):
            sys.stdout = _ThreadRoutedStream(sys.stdout)


@contextmanager
def capture_output():
    """Collect what this thread prints inside the block into a StringIO."""
    _install()
    previous = getattr(_local, "buffer", None)
    buffer = io.StringIO()
    _local.buffer = buffer
    try:
        yield buffer
    finally:
        _local.buffer = previous
