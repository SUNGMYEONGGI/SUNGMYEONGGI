#!/usr/bin/env python3
"""Read account usage locally and publish only validated daily aggregates to Gist."""
from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

from token_data import MAX_BYTES, dumps, from_usage, validate

ROOT = Path(__file__).resolve().parents[1]


def codex_binary():
    configured = os.environ.get("TOKEN_PROFILE_CODEX")
    if configured:
        if not Path(configured).is_file():
            raise RuntimeError("TOKEN_PROFILE_CODEX does not point to a file.")
        return configured
    found = shutil.which("codex")
    if found:
        return found
    candidates = glob.glob(str(Path.home() / ".vscode-server/extensions/openai.chatgpt-*/bin/linux-*/codex"))
    if candidates:
        return max(candidates, key=os.path.getmtime)
    raise RuntimeError("Codex is not installed. Set TOKEN_PROFILE_CODEX or add codex to PATH.")


def read_usage(timeout=90):
    # No thread is started and no inference runs. Authentication stays inside
    # Codex; this program never opens auth.json or session/chat history.
    proc = subprocess.Popen([codex_binary(), "app-server", "--listen", "stdio://"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    messages = queue.Queue(maxsize=128)

    def reader():
        try:
            while True:
                line = proc.stdout.readline(MAX_BYTES + 1)
                if not line:
                    messages.put(None)
                    return
                if len(line.encode("utf-8")) > MAX_BYTES:
                    messages.put(ValueError("Codex response is too large."))
                    return
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    messages.put(ValueError("Invalid Codex JSON response."))
                    return
        except (ValueError, OSError):
            messages.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def send(payload):
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def response(request_id):
        deadline = time.monotonic() + timeout
        while True:
            try:
                item = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("Codex usage request timed out.") from None
            if item is None:
                raise RuntimeError("Codex app-server closed before replying.")
            if isinstance(item, Exception):
                raise item
            if item.get("id") != request_id:
                continue
            if "error" in item:
                # Do not echo upstream text: it might contain sensitive details.
                raise RuntimeError(f"Codex request failed (code {item['error'].get('code')}). Check codex login status and version.")
            return item["result"]

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "token_profile", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True}}})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/usage/read"})
        return response(2)
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdin.close()
        thread.join(timeout=2)
        proc.stdout.close()


def gh_api(endpoint, *, payload=None):
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if payload is not None:
        args += ["--method", "PATCH", "--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError("GitHub request failed. Check gh auth status and gist permission.")
    if len(result.stdout.encode()) > MAX_BYTES * 2:
        raise RuntimeError("GitHub response is too large.")
    return json.loads(result.stdout)


def sync(config, usage):
    import re
    gist_id = config["gist_id"]
    if not re.fullmatch(r"[a-f0-9]{32}", gist_id):
        raise ValueError("Invalid gist ID.")
    gist = gh_api(f"gists/{gist_id}")
    if gist.get("owner", {}).get("login", "").lower() != config["github_owner"].lower():
        raise ValueError("Gist owner does not match profile configuration.")
    filename = "token-activity.json"
    file = gist.get("files", {}).get(filename)
    if file is None or file.get("truncated"):
        raise ValueError("Gist data is missing or truncated; refusing to overwrite it.")
    previous = json.loads(file["content"])
    data = from_usage(usage, previous)
    gh_api(f"gists/{gist_id}", payload={"files": {filename: {"content": dumps(data)}}})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["probe", "sync"])
    parser.add_argument("--config", type=Path, default=ROOT / "profile.json")
    parser.add_argument("--output", type=Path, help="Write only the public aggregate JSON locally")
    args = parser.parse_args()
    state = ROOT / ".local"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / "sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another sync is running; skipped.")
            return
        usage = read_usage()
        data = from_usage(usage)
        if args.command == "sync":
            config = json.loads(args.config.read_text())
            data = sync(config, usage)
        if args.output:
            args.output.write_text(dumps(data), encoding="utf-8")
        keys = sorted(data["days"])
        print(f"{'Published' if args.command == 'sync' else 'Read'} {len(keys)} daily buckets: {keys[0]} → {keys[-1]}")
        print(f"Latest bucket: {keys[-1]} / {data['days'][keys[-1]]:,} tokens")
        print("Lifetime:", f"{data['summary']['lifetimeTokens']:,}" if "lifetimeTokens" in data["summary"] else "unavailable")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        sys.exit(1)
