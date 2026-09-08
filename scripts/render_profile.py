#!/usr/bin/env python3
"""Generate GitHub-style token grass as self-contained, theme-aware SVG files."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request
from zoneinfo import ZoneInfo

from token_data import MAX_BYTES, validate

ROOT = Path(__file__).resolve().parents[1]
PALETTES = {
    "light": {"bg": "#ffffff", "text": "#1f2328", "muted": "#59636e", "border": "#d1d9e0",
              "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]},
    "dark": {"bg": "#0d1117", "text": "#f0f6fc", "muted": "#9198a1", "border": "#3d444d",
             "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]},
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def level(tokens):
    if tokens == 0:
        return 0
    if tokens < 10_000_000:
        return 1
    if tokens < 30_000_000:
        return 2
    if tokens < 100_000_000:
        return 3
    return 4


def grid_dates(today):
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    start = sunday - timedelta(weeks=52)
    return [start + timedelta(days=i) for i in range(53 * 7)]


def render_grass(data, theme, *, today=None, now=None):
    data = validate(data)
    now = now or datetime.now(timezone.utc)
    today = today or now.astimezone(ZoneInfo("Asia/Seoul")).date()
    cutoff = today - timedelta(days=364)
    days = data["days"]
    observed = {key: value for key, value in days.items() if cutoff <= date.fromisoformat(key) <= today}
    total = sum(observed.values())
    p = PALETTES[theme]
    updated = datetime.fromisoformat(data["updatedAt"].replace("Z", "+00:00")).astimezone(timezone.utc)
    stale = now - updated > timedelta(hours=48)
    title = f"{total:,} tokens in the last year"
    result = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="238" viewBox="0 0 900 238" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">Codex token activity. {len(observed)} recorded days. Each square is one day. Darkest green means at least 100 million tokens. Outlined squares mean no data. Daily dates are preserved from the account usage service.</desc>
  <style>text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: {p['muted']}; font-size: 11px; }}</style>
  <text x="1" y="22" style="font-size:16px;fill:{p['text']}">{title}</text>
  <text x="899" y="22" text-anchor="end">Codex · {len(observed)} recorded days</text>
  <rect x="0.5" y="40.5" width="899" height="171" rx="6" fill="{p['bg']}" stroke="{p['border']}"/>
''']
    dates = grid_dates(today)
    last_month = None
    last_column = -10
    for column in range(53):
        current = dates[column * 7]
        if current.month != last_month and column - last_column >= 3:
            result.append(f'<text x="{48 + column * 15}" y="63">{MONTHS[current.month - 1]}</text>')
            last_column = column
        last_month = current.month
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        result.append(f'<text x="15" y="{85 + row * 15}">{label}</text>')
    for i, current in enumerate(dates):
        column, row = divmod(i, 7)
        key = current.isoformat()
        attrs = f'x="{48 + column * 15}" y="{76 + row * 15}" width="12" height="12" rx="2" data-date="{key}"'
        if current > today or current < cutoff:
            result.append(f'<rect {attrs} fill="none" data-state="outside-window"/>')
        elif key not in days:
            result.append(f'<rect {attrs} fill="{p["bg"]}" stroke="{p["border"]}" stroke-opacity="0.5" stroke-width="0.6" data-state="unknown"><title>{key}: no data reported</title></rect>')
        else:
            tokens = days[key]
            result.append(f'<rect {attrs} fill="{p["levels"][level(tokens)]}" data-tokens="{tokens}" data-level="{level(tokens)}"><title>{key}: {tokens:,} tokens</title></rect>')
    result.append(f'<text x="16" y="196">Token Contributions</text>')
    result.append(f'<rect x="622" y="186" width="10" height="10" rx="2" fill="{p["bg"]}" stroke="{p["border"]}" stroke-width="0.6"/><text x="638" y="195">No data</text>')
    result.append('<text x="705" y="195">Less</text>')
    for i, color in enumerate(p["levels"]):
        result.append(f'<rect x="{734 + i * 15}" y="184" width="12" height="12" rx="2" fill="{color}"/>')
    result.append('<text x="816" y="195">More</text>')
    status = "Last sync" if not stale else "Sync delayed · last success"
    result.append(f'<text x="1" y="232">{status}: {escape(updated.strftime("%Y-%m-%d %H:%M UTC"))}</text>')
    result.append('<text x="899" y="232" text-anchor="end">Daily goal: 100,000,000 tokens</text>')
    result.append('</svg>\n')
    return '\n'.join(result)


def load_url(url):
    if not re.fullmatch(r"https://gist\.githubusercontent\.com/[A-Za-z0-9-]+/[a-f0-9]{32}/raw/token-activity\.json", url):
        raise ValueError("Expected a revision-free GitHub Gist raw token-activity.json URL.")
    request = urllib.request.Request(url, headers={"User-Agent": "token-profile/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.url.startswith("https://gist.githubusercontent.com/"):
            raise ValueError("Unexpected Gist redirect.")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Gist data exceeds size limit.")
    return validate(json.loads(payload))


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".svg-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--gist-url")
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    parser.add_argument("--today", type=date.fromisoformat, help="Override the window date for reproducible previews")
    args = parser.parse_args()
    if args.input and args.input.stat().st_size > MAX_BYTES:
        raise ValueError("Input exceeds size limit.")
    data = validate(json.loads(args.input.read_text())) if args.input else load_url(args.gist_url)
    now = datetime.now(timezone.utc)
    # Validate and generate both themes before touching either last-good file.
    outputs = {theme: render_grass(data, theme, today=args.today, now=now) for theme in PALETTES}
    for theme, svg in outputs.items():
        write_atomic(args.output / f"token-activity-{theme}.svg", svg)
    print(f"Rendered light/dark token activity from {len(data['days'])} recorded days.")


if __name__ == "__main__":
    main()
