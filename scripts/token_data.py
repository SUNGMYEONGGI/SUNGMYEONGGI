"""Validated, public-only token activity data. Python 3.10+, no dependencies."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

SOURCE = "codex/account/usage/read"
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
    if not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data["schemaVersion"] != 1:
        raise ValueError("Unsupported token activity schema.")
    if data.get("source") != SOURCE:
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
    raw_summary = data.get("summary", {})
    if not isinstance(raw_summary, dict):
        raise ValueError("summary must be an object.")
    summary = {key: count(raw_summary[key]) for key in SUMMARY_KEYS
               if raw_summary.get(key) is not None}
    # An allowlist prevents credentials, emails, thread IDs, or chat content from
    # accidentally entering a public gist even if the upstream response grows.
    return {"schemaVersion": 1, "source": SOURCE, "updatedAt": updated,
            "days": dict(sorted(days.items())), "summary": summary}


def from_usage(usage, previous=None, *, updated_at=None, through=None):
    buckets = usage.get("dailyUsageBuckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("dailyUsageBuckets is absent or empty; nothing was published.")
    days = {}
    for bucket in buckets:
        key = day(bucket["startDate"])
        if key in days:
            raise ValueError("Duplicate daily bucket; refusing ambiguous usage.")
        days[key] = count(bucket["tokens"])
    old = validate(previous)["days"] if previous is not None else {}
    # Buckets are cumulative snapshots. Replace overlapping dates, including
    # downward corrections; retain older dates outside the returned window.
    merged = {**old, **days}
    if through is not None:
        limit = day(through)
        merged = {key: value for key, value in merged.items() if key <= limit}
    return validate({"schemaVersion": 1, "source": SOURCE,
                     "updatedAt": updated_at or utc_now(),
                     "days": merged, "summary": usage.get("summary", {})})


def dumps(data):
    return json.dumps(validate(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
