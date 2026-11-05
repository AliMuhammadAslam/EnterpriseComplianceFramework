"""Tests that captured verbose output stays with the request that printed it.

Run with:  python -m unittest discover -s tests
"""

import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.output_capture import capture_output


class TestThreadIsolation(unittest.TestCase):

    def test_captures_this_threads_prints(self):
        with capture_output() as buf:
            print("hello")
        self.assertEqual(buf.getvalue(), "hello\n")

    def test_overlapping_captures_do_not_see_each_other(self):
        """Two threads printing at the same time each get only their own lines."""
        both_inside = threading.Barrier(2)
        results = {}

        def worker(name):
            with capture_output() as buf:
                both_inside.wait()
                for i in range(50):
                    print(f"{name}-{i}")
                both_inside.wait()
            results[name] = buf.getvalue().splitlines()

        threads = [threading.Thread(target=worker, args=(n,)) for n in ("alice", "bob")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results["alice"], [f"alice-{i}" for i in range(50)])
        self.assertEqual(results["bob"], [f"bob-{i}" for i in range(50)])

    def test_uncaptured_thread_is_not_swallowed(self):
        """A thread with no capture of its own keeps writing to the real stream."""
        real = io.StringIO()
        saved = sys.stdout
        try:
            sys.stdout = real
            started = threading.Event()
            release = threading.Event()

            def capturing():
                with capture_output():
                    started.set()
                    release.wait()

            t = threading.Thread(target=capturing)
            t.start()
            started.wait()
            print("from main thread")
            release.set()
            t.join()
        finally:
            sys.stdout = saved
        self.assertIn("from main thread", real.getvalue())

    def test_nested_capture_restores_the_outer_buffer(self):
        with capture_output() as outer:
            print("a")
            with capture_output() as inner:
                print("b")
            print("c")
        self.assertEqual(outer.getvalue(), "a\nc\n")
        self.assertEqual(inner.getvalue(), "b\n")


if __name__ == "__main__":
    unittest.main()
