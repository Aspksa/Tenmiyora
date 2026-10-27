"""Run every unittest in a named module and report individual durations.

The standard unittest runner still controls success/failure; a timing wrapper
only records elapsed monotonic time for each test (including failures).
"""
from __future__ import annotations

import argparse
import time
import unittest
from pathlib import Path
import sys


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.durations = []

    def startTest(self, test):
        self._started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.monotonic() - self._started
        self.durations.append((elapsed, test.id()))
        super().stopTest(test)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(root / "tests"), pattern=args.pattern,
        top_level_dir=str(root / "tests"))
    class Runner(unittest.TextTestRunner):
        resultclass = TimedResult
    result = Runner(verbosity=2).run(suite)
    print("Slowest individual tests:")
    for seconds, test_id in sorted(result.durations, reverse=True)[:3]:
        print(f"{seconds:.3f}s {test_id}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
