"""Explicit upgrade lifecycle coordination for a dedicated separated code tree.

The caller owns process shutdown and restart; callbacks must verify the exact
Tenmiyora instance. Never modifies .runtime, user documents, secrets or source
root. Installation remains restricted to a dedicated 'live' code directory.
"""
from pathlib import Path
from windows_offline_update import run as offline_run
from release_operator import operate
from release_staging import verify


def upgrade(root, package, live, backup, *, approved=False,
            stop=None, start=None, healthy=None, process_alive=None):
    if approved is not True:
        return {"updated":False, "phase":"approval_required"}
    if not all(callable(f) for f in (stop,start,healthy,process_alive)):
        return {"updated":False, "phase":"missing_lifecycle_callbacks"}
    if not verify(package):
        return {"updated":False, "phase":"invalid_package"}
    # Fail closed unless the original server can be safely stopped by its owner.
    if stop() is not True:
        return {"updated":False, "phase":"stop_failed"}
    # Once stopped, offline_run rechecks session PID, paths, package and backup.
    outcome=offline_run(root,package,live,backup,approved=True,
                        process_alive=process_alive)
    if not outcome.get("installed"):
        # Try to resume original server only after explicitly verified no changes.
        restored=start() is True
        return {"updated":False,"phase":"preflight_failed",
                "restarted_original":restored,"preflight":outcome.get("preflight")}
    try:
        running=start() is True
        checked=running and healthy() is True
    except Exception:
        checked=False
    if checked:
        return {"updated":True,"phase":"healthy",
                "rollback_available":Path(backup).exists()}
    # Health failure: stop the new version before reverting code.
    try:
        stopped=stop() is True
    except Exception:
        stopped=False
    if not stopped:
        return {"updated":False,"phase":"rollback_blocked_running",
                "backup_available":Path(backup).exists()}
    try:
        operate("rollback",live=live,backup=backup,approve=True)
    except Exception:
        return {"updated":False,"phase":"rollback_failed",
                "backup_available":Path(backup).exists()}
    try:
        resumed=start() is True and healthy() is True
    except Exception:
        resumed=False
    return {"updated":False,"phase":"rolled_back",
            "original_healthy":resumed}
