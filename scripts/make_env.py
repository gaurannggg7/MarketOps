"""Create a local .env from .env.example with freshly generated demo passwords.

Refuses to overwrite an existing .env. Passwords are written only to the gitignored .env file.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; leaving it unchanged.")
        return 0
    lines = []
    for line in (ROOT / ".env.example").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith("DEMO_") and key.endswith("_PASSWORD") and not value:
            line = f"{key}={secrets.token_urlsafe(18)}"
        lines.append(line)
    target.write_text("\n".join(lines) + "\n")
    target.chmod(0o600)
    print("Wrote .env with generated demo passwords (see DEMO_*_PASSWORD entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
