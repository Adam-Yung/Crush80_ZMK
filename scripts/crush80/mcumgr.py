"""Thin wrapper over the `mcumgr` CLI. Every call has a wall-clock timeout (see AGENTS.md)."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


class McumgrError(Exception):
    pass


@dataclass
class Slot:
    slot: int
    hash: str
    confirmed: bool
    active: bool
    pending: bool


def find_binary():
    found = shutil.which("mcumgr") or os.path.expanduser("~/go/bin/mcumgr")
    if not os.access(found, os.X_OK):
        raise McumgrError("mcumgr not found. Add it to scripts/owner/install-deps.sh and ask the owner to run it.")
    return found


def parse_image_list(text):
    """Parse `mcumgr image list` output (both the `flags:` and the `confirmed:/active:` styles)."""
    slots, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"image=(\d+)\s+slot=(\d+)", line)
        if m:
            cur = {"slot": int(m.group(2)), "hash": "", "flags": set(), "kv": {}}
            slots.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("hash:"):
            cur["hash"] = line.split(":", 1)[1].strip().lower()
        elif line.startswith("flags:"):
            cur["flags"] = set(line.split(":", 1)[1].split())
        elif ":" in line:
            key, val = line.split(":", 1)
            cur["kv"][key.strip()] = val.strip().lower() == "true"
    out = []
    for s in slots:
        def flag(name, s=s):
            return name in s["flags"] or s["kv"].get(name, False)
        out.append(Slot(s["slot"], s["hash"], flag("confirmed"), flag("active"), flag("pending")))
    return out


class Mcumgr:
    def __init__(self, port, binary=None, timeout=10):
        self.port = port
        self.binary = binary or find_binary()
        self.timeout = timeout

    def _run(self, args, limit):
        cmd = [self.binary, "--conntype", "serial", "--connstring", f"dev={self.port},baud=115200",
               "-t", str(self.timeout), "-r", "2"] + args
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            raise McumgrError(f"`mcumgr {' '.join(args)}` did not finish within {limit}s")
        if done.returncode != 0:
            raise McumgrError(f"`mcumgr {' '.join(args)}` failed: {(done.stdout + done.stderr).strip()}")
        return done.stdout

    def echo(self):
        self._run(["echo", "crush80"], limit=30)

    def image_list(self):
        return parse_image_list(self._run(["image", "list"], limit=60))

    def upload(self, path):
        self._run(["image", "upload", path], limit=600)

    def test(self, digest):
        self._run(["image", "test", digest], limit=60)

    def confirm(self, digest=""):
        self._run(["image", "confirm", digest], limit=60)

    def reset(self):
        self._run(["reset"], limit=30)
