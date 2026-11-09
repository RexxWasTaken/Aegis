"""AEGIS bot entry point."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from core.bot import AegisBot


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN in the runtime environment before starting AEGIS.")
    AegisBot().run(token)


if __name__ == "__main__":
    main()
