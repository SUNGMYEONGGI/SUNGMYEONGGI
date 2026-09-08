"""Aggregate local Claude Code usage metadata without publishing transcripts."""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from token_data import count

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def read_claude_days(config, state_dir):
    """Retain per-message counters locally so log cleanup cannot erase history.

    The ledger stores hashed message IDs, timestamps, and four counters only.
    Repeated/streaming records are cumulative snapshots of the same response;
    component-wise maxima retain its final recorded usage without adding copies.
    """
    directories = config.get("claude_data_dirs", [os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")])
    if not isinstance(directories, list) or not directories:
        raise ValueError("claude_data_dirs must contain Claude Code data directories.")
    paths = set()
    for directory in directories:
        projects = Path(directory).expanduser() / "projects"
        if not projects.is_dir():
            raise RuntimeError("Claude projects directory is unavailable; existing Gist was kept.")
        # Include subagent transcripts and retained superseded transcripts.
        for pattern in ("*/*.jsonl", "*/*.jsonl.superseded-*", "*/*/subagents/**/*.jsonl", "*/*/subagents/**/*.jsonl.superseded-*"):
            paths.update(path for path in projects.glob(pattern) if path.is_file())
    zone = ZoneInfo(config["display_timezone"])
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    ledger = state_dir / "claude-usage.sqlite3"
    with closing(sqlite3.connect(ledger, timeout=30)) as db:
        os.chmod(ledger, 0o600)
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            key TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
            input INTEGER NOT NULL, output INTEGER NOT NULL,
            cache_creation INTEGER NOT NULL, cache_read INTEGER NOT NULL
        )""")
        with db:
            for path in sorted(paths):
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            if not line.endswith("\n"):
                                # A running session may still be appending its last line.
                                continue
                            raise RuntimeError("Malformed Claude transcript; no aggregate was published.") from None
                        if not isinstance(record, dict) or record.get("type") != "assistant":
                            continue
                        message = record.get("message")
                        if not isinstance(message, dict) or message.get("model") == "<synthetic>":
                            continue
                        usage = message.get("usage")
                        if not isinstance(usage, dict):
                            continue
                        identifier = message.get("id")
                        if not isinstance(identifier, str) or not identifier:
                            raise ValueError("Claude usage record has no message ID for deduplication.")
                        timestamp = record.get("timestamp")
                        if not isinstance(timestamp, str):
                            raise ValueError("Claude usage record has no timestamp.")
                        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        if instant.tzinfo is None:
                            raise ValueError("Claude timestamps must include a timezone.")
                        stamp = instant.astimezone(timezone.utc).isoformat(timespec="microseconds")
                        if "input_tokens" not in usage or "output_tokens" not in usage:
                            raise ValueError("Claude usage counters are incomplete.")
                        values = [count(usage.get(field, 0)) for field in FIELDS]
                        key = hashlib.sha256(identifier.encode()).hexdigest()
                        db.execute("""INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(key) DO UPDATE SET
                              timestamp = min(timestamp, excluded.timestamp),
                              input = max(input, excluded.input),
                              output = max(output, excluded.output),
                              cache_creation = max(cache_creation, excluded.cache_creation),
                              cache_read = max(cache_read, excluded.cache_read)
                        """, [key, stamp, *values])
        days = defaultdict(int)
        for stamp, *values in db.execute("SELECT timestamp, input, output, cache_creation, cache_read FROM messages"):
            key = datetime.fromisoformat(stamp).astimezone(zone).date().isoformat()
            days[key] += sum(values)
        if not days:
            raise RuntimeError("No Claude usage metadata found; nothing was published.")
    return {key: count(value) for key, value in sorted(days.items())}
