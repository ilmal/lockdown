#!/usr/bin/env bash
# Push to GitHub, but only after re-checking everything tracked for secrets.
#
#   scripts/push.sh            # push existing commits
#   scripts/push.sh --commit   # also commit a dirty tree first
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "no 'origin' remote; add one with:" >&2
  echo "  git remote add origin git@github.com:ilmal/lockdown.git" >&2
  exit 1
fi

if [ "${1:-}" = "--commit" ] && [ -n "$(git status --porcelain)" ]; then
  git add -A
  if [ "${SKIP_SECRET_CHECK:-0}" != "1" ]; then
    ./scripts/check-secrets.sh
  fi
  git commit -m "auto-commit $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is dirty; commit or stash before pushing" >&2
  exit 1
fi

git push origin HEAD 2>&1 | tail -3
