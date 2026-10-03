"""Regression for MCP spawning after Printr wraps stderr."""

import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from services.printr import StreamToLogger


class LoggingStreamTests(unittest.TestCase):
    def test_subprocess_accepts_wrapped_stderr(self):
        # Test an actual OS descriptor, not a mock with a matching method name.
        with tempfile.TemporaryFile(mode="w+b") as stream:
            wrapper = StreamToLogger(logging.getLogger("elite-test"), stream=stream)
            self.assertEqual(stream.fileno(), wrapper.fileno())
            result = subprocess.run([sys.executable, "--version"], stderr=wrapper,
                                    stdout=subprocess.PIPE, check=True)
            self.assertIn(b"Python", result.stdout)


if __name__ == "__main__":
    unittest.main()
