"""Validated, public-only token activity data. Python 3.10+, no dependencies."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

CODEX_SOURCE = "codex/account/usage/read"
SOURCE = "codex+claude"
SCHEMA_VERSION = 2
MAX_BYTES = 2_000_000
SUMMARY_KEYS = ("lifetimeTokens", "peakDailyTokens", "currentStreakDays",
                "longestStreakDays", "longestRunningTurnSec")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def count(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("Token counts must be nonnegative 64-bit integers.")
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Dates must be YYYY-MM-DD.")
    date.fromisoformat(value)
    return value


def validate(data):
    if not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data["schemaVersion"] not in (1, SCHEMA_VERSION):
        raise ValueError("Unsupported token activity schema.")
    version = data["schemaVersion"]
    if data.get("source") != (CODEX_SOURCE if version == 1 else SOURCE):
        raise ValueError("Unexpected usage source.")
    updated = data.get("updatedAt")
    if not isinstance(updated, str):
        raise ValueError("updatedAt is required.")
    timestamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("updatedAt must include a timezone.")
    if not isinstance(data.get("days"), dict) or not data["days"]:
        raise ValueError("No daily usage buckets; existing data must be kept.")
    days = {day(k): count(v) for k, v in data["days"].items()}
    if version == SCHEMA_VERSION:
        raw_sources = data.get("sources")
        if not isinstance(raw_sources, dict) or set(raw_sources) != {"codex", "claude"}:
            raise ValueError("Combined usage must retain both source day maps.")
        sources = {}
        for name, values in raw_sources.items():
            if not isinstance(values, dict):
                raise ValueError("Source day maps must be objects.")
            sources[name] = dict(sorted((day(k), count(v)) for k, v in values.items()))
        expected = sum_sources(sources)
        if days != expected:
            raise ValueError("Combined daily totals do not match their sources.")
        return {"schemaVersion": SCHEMA_VERSION, "source": SOURCE, "updatedAt": updated,
                "days": dict(sorted(days.items())), "sources": sources,
                "summary": {"recordedTokens": sum(days.values()), "peakDailyTokens": max(days.values())}}
    raw_summary = data.get("summary", {})
    if not isinstance(raw_summary, dict):
        raise ValueError("summary must be an object.")
    summary = {key: count(raw_summary[key]) for key in SUMMARY_KEYS
               if raw_summary.get(key) is not None}
    # An allowlist prevents credentials, emails, thread IDs, or chat content from
    # accidentally entering a public gist even if the upstream response grows.
    return {"schemaVersion": 1, "source": CODEX_SOURCE, "updatedAt": updated,
            "days": dict(sorted(days.items())), "summary": summary}


def codex_days(usage):
    buckets = usage.get("dailyUsageBuckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("dailyUsageBuckets is absent or empty; nothing was published.")
    days = {}
    for bucket in buckets:
        key = day(bucket["startDate"])
        if key in days:
            raise ValueError("Duplicate daily bucket; refusing ambiguous usage.")
        days[key] = count(bucket["tokens"])
    return days


def sum_sources(sources):
    combined = {}
    for values in sources.values():
        for key, value in values.items():
            combined[key] = count(combined.get(key, 0) + value)
    return dict(sorted(combined.items()))


def combine_usage(usage, claude_days, previous=None, *, updated_at=None, through=None):
    latest_codex = codex_days(usage)
    latest_claude = {day(k): count(v) for k, v in claude_days.items()}
    if not latest_claude:
        raise ValueError("Claude day map is empty; existing combined data was kept.")
    old = validate(previous) if previous is not None else None
    if old is None:
        old_sources = {"codex": {}, "claude": {}}
    elif old["schemaVersion"] == 1:
        # The old gist's totals belong entirely to Codex. Migrate them once.
        old_sources = {"codex": old["days"], "claude": {}}
    else:
        old_sources = old["sources"]
    for key, value in old_sources["claude"].items():
        if latest_claude.get(key, -1) < value:
            raise ValueError("Claude usage ledger is incomplete. Restore .local/claude-usage.sqlite3 before syncing.")
    # Buckets are cumulative snapshots. Replace overlapping dates, including
    # downward corrections; retain older dates outside the returned window.
    sources = {"codex": {**old_sources["codex"], **latest_codex}, "claude": latest_claude}
    if through is not None:
        limit = day(through)
        sources = {name: {key: value for key, value in days.items() if key <= limit}
                   for name, days in sources.items()}
    return validate({"schemaVersion": SCHEMA_VERSION, "source": SOURCE,
                     "updatedAt": updated_at or utc_now(),
                     "days": sum_sources(sources), "sources": sources})


def dumps(data):
    return json.dumps(validate(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
