#!/usr/bin/env bash
# Lightweight committed-secret check over git-tracked files. Not a substitute for a dedicated
# scanner (e.g. gitleaks) in CI; it catches the obvious mistakes this project could make.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
status=0
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked by git"; status=1
fi
patterns='(BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]+|sk-[A-Za-z0-9]{32,}|DEMO_[A-Z0-9]+_PASSWORD=[A-Za-z0-9_-]{8,})'
if git ls-files -z | xargs -0 grep -nEI "$patterns" -- 2>/dev/null | grep -v '^scripts/secret_scan.sh:'; then
  echo "FAIL: possible secret material in tracked files (see above)"; status=1
fi
[ $status -eq 0 ] && echo "secret scan: no findings in $(git ls-files | wc -l | tr -d ' ') tracked files"
exit $status
