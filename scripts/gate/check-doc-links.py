#!/usr/bin/env python3
"""Fail if a `docs/...` path or a relative markdown link in docs, AGENTS.md or README.md points at nothing."""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN = ["AGENTS.md", "CLAUDE.md", "README.md", "docs", ".cursor"]
DOC_PATH = re.compile(r"(?<![\w/.-])(docs/[\w./-]*[\w/])")
MD_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def files():
    for entry in SCAN:
        full = os.path.join(REPO, entry)
        if os.path.isfile(full):
            yield full
        for root, _dirs, names in os.walk(full):
            for n in names:
                if n.endswith((".md", ".mdc")):
                    yield os.path.join(root, n)


def main():
    bad = []
    for path in files():
        text = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, REPO)
        if rel.startswith("docs/history/") or rel.startswith("docs/decisions/"):
            continue  # append-only or finished: old paths stay as written
        for m in DOC_PATH.finditer(text):
            if "<" in m.group(1) or "*" in m.group(1):
                continue
            if not os.path.exists(os.path.join(REPO, m.group(1))):
                bad.append(f"{rel}: {m.group(1)}")
        for m in MD_LINK.finditer(text):
            target = m.group(1)
            if "://" in target or target.startswith("mailto:"):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), target))):
                bad.append(f"{rel}: link {target}")
    for b in sorted(set(bad)):
        print("BROKEN", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
