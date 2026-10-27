"""Isolated executable checks for candidate recovery procedures.

These are synthetic, controlled checks; never attribute production recoveries
to a method without production provenance.
"""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from soul_method_evidence import DEFAULT_METHODS, record_test, evaluate


def probe(category, method):
    if category == "disk_save_failed" and method in ("check_path", "retry_write"):
        with TemporaryDirectory() as root:
            target = Path(root) / "probe.txt"
            if method == "check_path":
                return target.parent.is_dir() and not target.exists()
            target.write_text("recovery-probe", encoding="utf-8")
            return target.read_text(encoding="utf-8") == "recovery-probe"
    if category == "document_source_changed" and method in ("refresh_hash", "rerun_analysis"):
        with TemporaryDirectory() as root:
            target = Path(root) / "document.txt"
            target.write_text("before", encoding="utf-8")
            original = hashlib.sha256(target.read_bytes()).hexdigest()
            target.write_text("after", encoding="utf-8")
            updated = hashlib.sha256(target.read_bytes()).hexdigest()
            if method == "refresh_hash":
                return original != updated
            # A new run must use the updated source hash and reject stale state.
            return original != updated and updated == hashlib.sha256(target.read_bytes()).hexdigest()
    raise ValueError("Unknown candidate")


def run_exam():
    state = DEFAULT_METHODS
    for category, methods in (
        ("disk_save_failed", ("check_path", "retry_write")),
        ("document_source_changed", ("refresh_hash", "rerun_analysis")),
    ):
        for method in methods:
            for _ in range(3):
                result = probe(category, method)
                state = record_test(state, category, method, result, verified=True)
    return {"scope":"isolated_synthetic_only",
            "records":evaluate(state)}


def main():
    report = run_exam()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(row["status"] != "repeat_test_supported" for row in report["records"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
