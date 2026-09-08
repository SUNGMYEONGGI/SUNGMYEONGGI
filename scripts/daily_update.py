#!/usr/bin/env python3
"""Once per local day: sync through yesterday, then dispatch image generation."""
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from sync_usage import ROOT, read_usage, sync


def save_state(path, state):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".daily-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    config = json.loads((ROOT / "profile.json").read_text())
    zone = ZoneInfo(config["display_timezone"])
    through = (datetime.now(zone).date() - timedelta(days=1)).isoformat()
    state_dir = ROOT / ".local"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    state_path = state_dir / "daily-update.json"
    # Share the lock with manual syncs, too.
    with (state_dir / "sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another token sync is running. Retry after it finishes.") from None
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get("through") == through and state.get("dispatched"):
            print(f"Daily update through {through} already dispatched; skipped.")
            return
        if state.get("through") != through or not state.get("synced"):
            data = sync(config, read_usage(), through=through)
            state = {"through": through, "synced": True, "dispatched": False}
            save_state(state_path, state)
            print(f"Published {len(data['days'])} daily records through {through}.")
            if through not in data["days"]:
                print(f"Upstream has not reported {through}; latest record is {max(data['days'])}. Missing data was kept unknown.")
        # A dispatch failure can be retried without collecting/publishing twice.
        result = subprocess.run([
            "gh", "workflow", "run", "token-grass.yml",
            "--repo", config["profile_repository"], "--ref", "main",
            "--field", f"through_date={through}",
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError("Image dispatch failed. Run daily_update.py again to retry dispatch without resyncing.")
        state["dispatched"] = True
        save_state(state_path, state)
        print(f"Dispatched token grass through {through}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Daily update failed: {exc}", file=sys.stderr)
        sys.exit(1)
