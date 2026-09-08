"""Offline regressions for usage integrity and generated-branch publishing."""
import copy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_profile as render
import sync_usage as sync
from token_data import from_usage, validate

NOW = datetime(2026, 9, 8, 14, tzinfo=timezone.utc)
NS = {"s": "http://www.w3.org/2000/svg"}


def usage():
    return {"summary": {"lifetimeTokens": 110_000_000}, "dailyUsageBuckets": [
        {"startDate": "2026-09-06", "tokens": 0},
        {"startDate": "2026-09-07", "tokens": 110_000_000}]}


def data():
    return from_usage(usage(), updated_at="2026-09-08T14:00:00Z")


class DataTests(unittest.TestCase):
    def test_snapshots_replace_without_double_counting_and_allow_corrections(self):
        old = data()
        updated = usage()
        updated["dailyUsageBuckets"] = [{"startDate": "2026-09-07", "tokens": 90_000_000}]
        actual = from_usage(updated, old)
        self.assertEqual(actual["days"], {"2026-09-06": 0, "2026-09-07": 90_000_000})
        self.assertEqual(from_usage(updated, actual)["days"], actual["days"])

    def test_missing_usage_cannot_erase_history(self):
        old = data()
        for buckets in (None, [], {}):
            with self.subTest(buckets=buckets), self.assertRaises(ValueError):
                from_usage({"dailyUsageBuckets": buckets}, old)
        self.assertEqual(old, data())

    def test_invalid_dates_counts_and_duplicate_buckets_are_rejected(self):
        for value in (-1, True, 1.2, "100", None, 2**63):
            broken = usage()
            broken["dailyUsageBuckets"][0]["tokens"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                from_usage(broken)
        for key in ("2026-02-30", "20260907", "<script>"):
            broken = usage()
            broken["dailyUsageBuckets"][0]["startDate"] = key
            with self.subTest(key=key), self.assertRaises(ValueError):
                from_usage(broken)
        broken = usage()
        broken["dailyUsageBuckets"].append(broken["dailyUsageBuckets"][0])
        with self.assertRaises(ValueError):
            from_usage(broken)

    def test_only_public_aggregate_fields_survive(self):
        raw = usage()
        raw.update({"accessToken": "secret", "email": "private", "threadUsage": {"threadId": "private"}})
        raw["summary"]["secret"] = "private"
        serialized = json.dumps(from_usage(raw))
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private", serialized)
        raw["summary"]["peakDailyTokens"] = None
        self.assertNotIn("peakDailyTokens", from_usage(raw)["summary"])

    def test_foreign_source_or_untrusted_timestamp_is_rejected(self):
        for field, value in (("source", "unknown"), ("updatedAt", "2026-09-08"), ("schemaVersion", True)):
            broken = data()
            broken[field] = value
            with self.assertRaises(ValueError):
                validate(broken)


class CollectorTests(unittest.TestCase):
    def test_gist_updates_only_intended_file_with_merged_counts(self):
        gist = {"owner": {"login": "SUNGMYEONGGI"}, "files": {
            "token-activity.json": {"content": json.dumps(data())}, "other.txt": {"content": "keep"}}}
        with patch.object(sync, "gh_api", side_effect=[gist, {}]) as api:
            sync.sync({"github_owner": "SUNGMYEONGGI", "gist_id": "a" * 32}, usage())
        payload = api.call_args.kwargs["payload"]
        self.assertEqual(list(payload["files"]), ["token-activity.json"])
        self.assertEqual(json.loads(payload["files"]["token-activity.json"]["content"])["days"], data()["days"])

    def test_wrong_owner_and_truncated_gist_never_write(self):
        for owner, truncated in (("someone_else", False), ("SUNGMYEONGGI", True)):
            gist = {"owner": {"login": owner}, "files": {"token-activity.json": {
                "content": json.dumps(data()), "truncated": truncated}}}
            with patch.object(sync, "gh_api", return_value=gist) as api, self.assertRaises(ValueError):
                sync.sync({"github_owner": "SUNGMYEONGGI", "gist_id": "a" * 32}, usage())
            self.assertEqual(api.call_count, 1)


class RenderTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual([render.level(n) for n in [0, 1, 9_999_999, 10_000_000,
                         29_999_999, 30_000_000, 99_999_999, 100_000_000]], [0, 1, 1, 2, 2, 3, 3, 4])

    def test_grid_has_53_weeks_and_distinguishes_unknown_zero_and_future(self):
        for theme in render.PALETTES:
            xml = ET.fromstring(render.render_grass(data(), theme, today=date(2026, 9, 8), now=NOW))
            cells = {e.attrib["data-date"]: e.attrib for e in xml.findall("s:rect", NS) if "data-date" in e.attrib}
            self.assertEqual(len(cells), 371)
            self.assertEqual(cells["2026-09-06"]["data-tokens"], "0")
            self.assertEqual(cells["2026-09-07"]["data-level"], "4")
            self.assertEqual(cells["2026-09-08"]["data-state"], "unknown")
            self.assertEqual(cells["2026-09-09"]["data-state"], "outside-window")
            self.assertIn("110,000,000 tokens", xml.find("s:title", NS).text)

    def test_rolling_total_excludes_old_data_and_stale_data_is_visible(self):
        sample = data()
        sample["days"]["2020-01-01"] = 999_999_999
        sample["updatedAt"] = "2026-09-01T00:00:00Z"
        svg = render.render_grass(sample, "light", today=date(2026, 9, 8), now=NOW)
        self.assertIn("110,000,000 tokens in the last year", svg)
        self.assertIn("Sync delayed", svg)

    def test_year_boundaries_and_leap_day(self):
        for today in (date(2024, 2, 29), date(2026, 1, 1), date(2026, 9, 6), date(2026, 9, 12)):
            days = render.grid_dates(today)
            self.assertEqual(len(days), 371)
            self.assertEqual(days[0].weekday(), 6)
            self.assertIn(today, days)


class PublishTests(unittest.TestCase):
    def test_publishing_preserves_main_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args, cwd=None):
                return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
            remote, repo = root / "origin.git", root / "repo"
            git("init", "--bare", str(remote))
            git("init", "-b", "main", str(repo))
            git("config", "user.name", "Test", cwd=repo)
            git("config", "user.email", "test@example.invalid", cwd=repo)
            (repo / "README.md").write_text("Existing profile\n")
            git("add", ".", cwd=repo)
            git("commit", "-m", "initial", cwd=repo)
            git("remote", "add", "origin", str(remote), cwd=repo)
            git("push", "origin", "main", "main:token-assets", cwd=repo)
            main_sha = git("rev-parse", "main", cwd=repo)
            output = root / "output"
            output.mkdir()
            for theme in ("light", "dark"):
                (output / f"token-activity-{theme}.svg").write_text(render.render_grass(data(), theme, now=NOW))
            env = {**os.environ, "TOKEN_OUTPUT": str(output), "TOKEN_PUBLISH": str(root / "publish")}
            shas = []
            for _ in range(2):
                subprocess.run(["bash", str(ROOT / "scripts/publish_assets.sh")], cwd=repo, env=env,
                               check=True, capture_output=True, text=True)
                shas.append(git("rev-parse", "refs/heads/token-assets", cwd=remote))
            self.assertEqual(shas[0], shas[1])
            self.assertEqual(git("rev-parse", "refs/heads/main", cwd=remote), main_sha)
            self.assertEqual((repo / "README.md").read_text(), "Existing profile\n")
            self.assertFalse((root / "publish").exists())


if __name__ == "__main__":
    unittest.main()
