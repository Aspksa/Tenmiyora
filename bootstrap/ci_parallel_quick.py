"""Run two independent, isolated test suites concurrently; fail if either fails.

Each suite uses its own subprocess and the existing unittest discovery.
Full CI coverage and test selection are unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time


SUITES = (
    ("Целостность лаборатории", "test_brain_lab_integrity.py"),
    ("Негативные сценарии", "test_brain_lab_adversarial.py"),
)


def run_suite(label, pattern):
    started = time.monotonic()
    command = [sys.executable, "bootstrap/ci_unittest_profile.py", "--pattern", pattern]
    finished = subprocess.run(command, check=False, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    return label, finished.returncode, time.monotonic() - started, finished.stdout, finished.stderr


def main():
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_suite, *suite) for suite in SUITES]
        results = [future.result() for future in futures]
    failed = False
    for label, code, seconds, output, errors in results:
        print(f"=== {label}: {seconds:.2f}s, exit={code} ===", flush=True)
        print(output, end="", flush=True)
        print(errors, end="", file=sys.stderr, flush=True)
        failed |= code != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
