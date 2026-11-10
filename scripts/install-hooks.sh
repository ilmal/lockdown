#!/usr/bin/env bash
# One-time, per-clone: route git hooks into the versioned .githooks dir.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x .githooks/* scripts/*.sh
git config core.hooksPath .githooks
echo "hooks installed: $(git config core.hooksPath)"
