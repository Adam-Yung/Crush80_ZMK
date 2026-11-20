#!/bin/bash
# Pre-commit gate. Everything here runs offline and finishes in seconds. A commit does not land unless this is green.
# Firmware compilation is NOT part of this gate (needs the west workspace); see docs/guides/build.md.
set -u
cd "$(dirname "$0")/../.."
fail=0
step() { echo "== $*"; }
run() { perl -e 'alarm shift; exec @ARGV' 120 "$@" || { echo "FAILED: $*"; fail=1; }; }

step "python tests"
run python3 -I -c "import sys; sys.path.insert(0,'scripts'); import unittest; unittest.main(module=None, argv=['x','discover','-s','scripts/tests','-t','scripts'])"

step "shell syntax"
for f in *.sh scripts/*.sh scripts/*/*.sh patches/*.sh crush80; do [ -f "$f" ] && { run bash -n "$f"; }; done

step "python syntax"
for f in scripts/*.py scripts/*/*.py scripts/crush80/*.py; do [ -f "$f" ] && { run python3 -I -m py_compile "$f"; }; done

step "doc links"
run python3 -I scripts/gate/check-doc-links.py

step "known-good images"
run ./crush80 golden

step "kconfig/dts sanity (greps, not a compile)"
if grep -rn "aw20216s\|AW20216S" zmk conf --include=* -l 2>/dev/null | grep -q .; then
    echo "FAILED: stale AW20216S references in zmk/ or conf/"; fail=1
fi

[ $fail -eq 0 ] && echo "GATE PASSED" || echo "GATE FAILED"
exit $fail
