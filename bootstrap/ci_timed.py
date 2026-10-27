"""Measure CI command wall time without changing its exit status.

Writes a compact per-job Markdown summary in GitHub Actions. No secrets,
source documents or command output are included in the timing report.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description="Time a CI command")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--label")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    timings_path = Path(".runtime/ci-timings.jsonl")
    if args.report:
        rows = []
        if timings_path.is_file():
            for line in timings_path.read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
        rows.sort(key=lambda item: item["seconds"], reverse=True)
        print("Top 3 CI steps by command wall time:")
        for row in rows[:3]:
            print(f'{row["label"]}: {row["seconds"]:.2f}s ({row["status"]})')
        timings_path.parent.mkdir(parents=True, exist_ok=True)
    with timings_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"label": args.label.replace("|", "/"), "seconds": round(elapsed, 3), "status": status}, ensure_ascii=False) + "\\n".replace("\\\\n", "\\n"))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write("### Три самых медленных измеренных этапа\\n\\n".replace("\\\\n", "\\n"))
                output.write("| Этап | Секунды | Статус |\\n|---|---:|---|\\n".replace("\\\\n", "\\n"))
                for row in rows[:3]:
                    output.write(f'| {row["label"]} | {row["seconds"]:.2f} | {row["status"]} |\\n'.replace("\\\\n", "\\n"))
        return 0
    if not args.label or not command:
        parser.error("--label and command are required unless --report is used")
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
                output.write("| Этап | Секунды | Результат |\n|---|---:|---|\n")
                output.write(f"| {safe_label} | {elapsed:.2f} | {status} |\n")
        except OSError as exc:
            print(f"Warning: could not write CI timing summary: {exc}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
