#!/usr/bin/env python3
"""Install/remove the hourly Linux user timer. Requires an existing Codex/gh login."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT = "github-token-profile"


def quote(value):
    # systemd specifiers and environment variables have their own expansion.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "uninstall"])
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("This installer is for Linux/systemd.")
    units = Path.home() / ".config/systemd/user"
    if args.command == "uninstall":
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT + ".timer"], check=True)
        subprocess.run(["systemctl", "--user", "stop", UNIT + ".service"], check=True)
        for suffix in ("service", "timer"):
            (units / f"{UNIT}.{suffix}").unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        return
    if not (ROOT / "profile.json").exists():
        parser.error("Configure profile.json before installing the timer.")
    units.mkdir(parents=True, exist_ok=True)
    local_path = str(Path.home() / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin:/snap/bin"
    service = f'''[Unit]
Description=Sync Codex daily token activity to GitHub Gist
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={str(ROOT).replace('%', '%%')}
Environment="PATH={local_path}"
ExecStart={quote(sys.executable)} {quote(ROOT / 'scripts/sync_usage.py')} sync
TimeoutStartSec=240
UMask=0077
'''
    timer = '''[Unit]
Description=Refresh GitHub token activity every hour

[Timer]
OnCalendar=*-*-* *:07:00
Persistent=true
RandomizedDelaySec=30
Unit=github-token-profile.service

[Install]
WantedBy=timers.target
'''
    (units / f"{UNIT}.service").write_text(service)
    (units / f"{UNIT}.timer").write_text(timer)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT + ".timer"], check=True)
    print("Installed hourly timer (:07 local time); missed runs resume when the user service starts.")


if __name__ == "__main__":
    main()
