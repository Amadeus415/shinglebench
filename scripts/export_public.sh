#!/bin/sh
# Build a public mirror of the repo WITHOUT held-out tasks.
# Relies on `tasks/heldout/** export-ignore` in .gitattributes, then double-checks for leaks.
# dist/public is the working copy of the public GitHub repo: its .git is kept, so after an
# export you can `cd dist/public && git add -A && git commit && git push`.
set -eu
out="dist/public"
mkdir -p "$out"
find "$out" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD | tar -x -C "$out"
if [ -n "$(ls -A "$out/tasks/heldout" 2>/dev/null)" ]; then echo "FAIL: held-out tasks leaked into $out"; exit 1; fi
if grep -rEl "shinglebench-canary:[0-9a-f]{8}" "$out" >/dev/null 2>&1; then echo "FAIL: a held-out canary string is present in $out"; exit 1; fi
echo "public export written to $out (held-out tasks excluded)"
