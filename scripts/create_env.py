#!/usr/bin/env python3
"""Create a local .env from .env.example, with a fresh random value for every secret.

    python scripts/create_env.py           # create .env (refuses to overwrite)
    python scripts/create_env.py --force   # replace an existing .env

Works with the Python standard library only; nothing to install.
"""

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / ".env.example"
TARGET = ROOT / ".env"
PLACEHOLDER = "change-me"


def fill(template: str) -> tuple[str, list[str]]:
    lines, filled = [], []
    for line in template.splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and value.strip() == PLACEHOLDER:
            # Every secret gets its own value; nothing is shared or reused.
            line = f"{key}={secrets.token_urlsafe(48)}"
            filled.append(key.strip())
        lines.append(line)
    return "\n".join(lines) + "\n", filled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = parser.parse_args()

    if TARGET.exists() and not args.force:
        print(f"{TARGET.name} already exists. Use --force to replace it (your current keys will be lost).")
        return 1

    content, filled = fill(TEMPLATE.read_text())
    TARGET.write_text(content)
    try:
        TARGET.chmod(0o600)  # readable by you only
    except OSError:
        pass  # e.g. on Windows

    print(f"Created {TARGET.name} with new random values for: {', '.join(filled)}")
    print()
    print("Note: Postgres only sets its password when its data volume is first created.")
    print("If you have run the project before with a different POSTGRES_PASSWORD, either put")
    print("the old password back in .env, or reset the database (this deletes local data;")
    print("the demo catalogue is re-created automatically):")
    print("    docker compose down -v")
    print()
    print("Next: docker compose up -d --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
