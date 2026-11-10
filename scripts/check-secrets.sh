#!/usr/bin/env bash
# Fail if anything staged looks like a secret. Public repo: last line of defence.
set -uo pipefail

fail=0

# Patterns that must never appear in a public repo.
declare -a PATTERNS=(
  'BEGIN [A-Z ]*PRIVATE KEY'
  'AKIA[0-9A-Z]{16}'
  'gh[pousr]_[A-Za-z0-9]{36,}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'tskey-[A-Za-z0-9-]{10,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
  'sk-[A-Za-z0-9]{20,}'
  'sk-ant-[A-Za-z0-9-]{20,}'
  'AIza[0-9A-Za-z_-]{35}'
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}'
  '100\.(6[4-9]|[7-9][0-9]|1[0-2][0-9])\.[0-9]{1,3}\.[0-9]{1,3}'
  'NilsGustav'
  '/home/nils'
  '(password|passwd|passphrase|secret|api[_-]?key|auth[_-]?token|bearer)[[:space:]]*[=:][[:space:]]*["'"'"'][^"'"'"']{8,}["'"'"']'
)

# Files that legitimately contain the patterns above (this scanner itself).
ALLOW='scripts/check-secrets.sh'

scan_text() {
  local label="$1" text="$2" pattern
  for pattern in "${PATTERNS[@]}"; do
    if printf '%s' "$text" | grep -EqI -- "$pattern"; then
      echo "  x $label: matches /$pattern/" >&2
      printf '%s' "$text" | grep -nEI -- "$pattern" | head -3 | sed 's/^/      /' >&2
      fail=1
    fi
  done
}

git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repo" >&2; exit 1; }

staged=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)

for file in $staged; do
  [ -f "$file" ] || continue
  [ "$file" = "$ALLOW" ] && continue
  case "$file" in
    *.jpg|*.jpeg|*.png|*.npy|*.npz|*.tar|*.zip|*.AppImage) continue ;;
  esac
  scan_text "$file" "$(cat -- "$file")"
done

if [ -n "$staged" ] && printf '%s\n' "$staged" \
    | grep -qE '^(\.env|.*\.pem|.*\.key|.*\.p12|.*token.*|.*\.crt)$'; then
  echo "  x staged file name looks like a credential:" >&2
  printf '%s\n' "$staged" | grep -E '^(\.env|.*\.pem|.*\.key|.*\.p12|.*token.*|.*\.crt)$' \
    | sed 's/^/      /' >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  cat >&2 <<'EOF'

Refusing to continue: the content above looks like a secret.
This repository is PUBLIC. Remove it, or if it is a false positive,
commit with SKIP_SECRET_CHECK=1 and say why in the commit message.
EOF
  exit 1
fi

exit 0
