"""Time CI commands and display the three slowest measured stages per job."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TIMINGS = Path(".runtime/ci-timings.jsonl")


def summary_line(message):
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        try:
            with Path(destination).open("a", encoding="utf-8") as stream:
                stream.write(message)
        except OSError as error:
            print(f"Could not write CI summary: {error}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Time a CI command")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--label")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.report:
        rows = []
        if TIMINGS.is_file():
            for line in TIMINGS.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    if isinstance(row["seconds"], (int, float)):
                        rows.append(row)
                except (ValueError, KeyError, TypeError):
                    continue
        rows.sort(key=lambda row: row["seconds"], reverse=True)
        print("Top 3 measured CI stages:")
        report = "### Три самых медленных этапа (команды)\n\n| Этап | Секунды | Статус |\n|---|---:|---|\n"
        for row in rows[:3]:
            print(f'{row["label"]}: {row["seconds"]:.2f}s ({row["status"]})')
            report += f'| {row["label"]} | {row["seconds"]:.2f} | {row["status"]} |\n'
        if not rows:
            report += "| Нет измерений | — | — |\n"
        summary_line(report)
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.label or not command:
        parser.error("--label and command are required unless --report is used")
    start = time.monotonic()
    try:
        code = subprocess.run(command, check=False).returncode
    except OSError as error:
        print(f"CI command could not start: {error}", file=sys.stderr)
        code = 127
    elapsed = time.monotonic() - start
    label = args.label.replace("|", "/").replace("\n", " ")
    status = "OK" if code == 0 else f"FAIL ({code})"
    print(f"[CI timing] {label}: {elapsed:.2f}s — {status}", flush=True)
    TIMINGS.parent.mkdir(parents=True, exist_ok=True)
    with TIMINGS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"label": label, "seconds": round(elapsed, 3),
                                 "status": status}, ensure_ascii=False) + "\n")
    summary_line(f"| {label} | {elapsed:.2f} | {status} |\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
