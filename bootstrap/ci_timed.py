"""Measure CI command wall time without changing its exit status.

Writes a compact per-job Markdown summary in GitHub Actions. No secrets,
source documents or command output are included in the timing report.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description="Time a CI command")
    parser.add_argument("--label", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command is required after --")
    started = time.monotonic()
    try:
        result = subprocess.run(command, check=False)
        code = result.returncode
    except OSError as exc:
        print(f"Could not run CI command: {exc}", file=sys.stderr)
        code = 127
    elapsed = time.monotonic() - started
    status = "OK" if code == 0 else f"FAIL ({code})"
    print(f"[CI timing] {args.label}: {elapsed:.2f}s — {status}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        safe_label = args.label.replace("|", "/").replace("\n", " ")
        try:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write(f"| {safe_label} | {elapsed:.2f} | {status} |\n")
        except OSError as exc:
            print(f"Warning: could not write CI timing summary: {exc}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
