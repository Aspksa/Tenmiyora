"""Deterministic unittest sharding for slow Windows CI runners.

Every discovered test ID belongs to exactly one SHA-256 shard. Import
failures remain test cases and cannot be hidden. All shards must succeed.
No user workspace, cloud provider, or test data is inspected by this runner.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def flatten(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from flatten(entry)
        else:
            yield entry


def select_cases(cases, shard, total):
    if type(shard) is not int or type(total) is not int or total < 1 or not 0 <= shard < total:
        raise ValueError("Invalid shard number or total.")
    return [case for case in cases if
        int.from_bytes(hashlib.sha256(case.id().encode("utf-8")).digest()[:8],
                       byteorder="big") % total == shard]


def discover():
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT / "tests"),
                            pattern="test_*.py",
                            top_level_dir=str(ROOT / "tests"))
    return list(flatten(suite))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Unittest shard for Tenmiyora CI.")
    parser.add_argument("--shard", required=True, type=int)
    parser.add_argument("--total", required=True, type=int)
    args = parser.parse_args(argv)
    if args.total > 16 or args.total < 1 or args.shard < 0 or args.shard >= args.total:
        parser.error("shard must be within 0..total-1 and total within 1..16")
    tests = discover()
    chosen = select_cases(tests, args.shard, args.total)
    print(f"CI shard {args.shard + 1}/{args.total}: "
          f"{len(chosen)} of {len(tests)} tests discovered", flush=True)
    if not chosen:
        return 1
    # Failed imports are returned by unittest discover as failing test cases,
    # not omitted. Every shard independently loads the same suite but only
    # runs the selected test cases.
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(chosen))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
