"""Explicit offline release operator for a STOPPED dedicated code directory.

Usage:
  python bootstrap/release_operator.py verify --package PATH
  python bootstrap/release_operator.py install --package PATH --live PATH --backup PATH --approve
  python bootstrap/release_operator.py rollback --live PATH --backup PATH --approve

Not wired to a running web server or Windows launcher. Keep .runtime and user
storage OUTSIDE the managed --live directory. No network or silent restart.
"""
import argparse
import ast
import json
from pathlib import Path
from release_staging import verify
from release_transaction import install, rollback


def health(root):
    """Basic static code validation, NOT a runtime/service health guarantee."""
    base = Path(root)
    modules = list(base.rglob("*.py"))
    if not modules:
        return False
    try:
        for path in modules:
            if path.is_symlink() or any(p.startswith(".") for p in path.relative_to(base).parts):
                return False
            ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, ValueError, SyntaxError):
        return False
    return True


def operate(action, *, package=None, live=None, backup=None, approve=False):
    if action == "verify":
        if package is None:
            raise ValueError("Missing package")
        return {"verified": verify(package), "executed": False}
    if not approve:
        raise PermissionError("Explicit --approve required")
    if live is None or backup is None:
        raise ValueError("Live and backup paths required")
    if action == "install":
        if package is None or not health(package):
            raise ValueError("Package has no valid Python sources")
        result = install(package, live, backup, approved=True, health_check=health)
        result["runtime_health_verified"] = False
        return result
    if action == "rollback":
        if not health(backup):
            raise ValueError("Rollback package has no valid Python sources")
        result = rollback(live, backup, approved=True)
        result["runtime_health_verified"] = False
        return result
    raise ValueError("Unknown operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline Tenmiyora release operator")
    parser.add_argument("action", choices=("verify","install","rollback"))
    parser.add_argument("--package")
    parser.add_argument("--live")
    parser.add_argument("--backup")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = operate(args.action, package=args.package, live=args.live,
                         backup=args.backup, approve=args.approve)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("verified", True) else 1
    except (PermissionError, ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
