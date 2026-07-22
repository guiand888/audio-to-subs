"""Admin CLI for audio_to_subs.

Subcommands: db-init, whoami
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from sqlalchemy import select

from audio_to_subs.db.models import User
from audio_to_subs.db.session import get_async_session

logger = logging.getLogger(__name__)


async def cmd_db_init(args: argparse.Namespace) -> int:
    """Initialize database with migrations."""
    import subprocess

    print("Running database migrations...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=args.cwd or ".",
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error running migrations: {result.stderr}", file=sys.stderr)
        return 1

    print("Database initialized successfully")
    return 0


async def cmd_whoami(args: argparse.Namespace) -> int:
    """List users (diagnostic)."""
    async with get_async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        if not users:
            print("No users found")
            return 0

        print(f"Found {len(users)} user(s):")
        for user in users:
            print(f"  - {user.username} (id={user.id})")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m audio_to_subs.admin",
        description="Admin CLI for audio_to_subs",
    )
    subparsers = parser.add_subparsers(dest="command")

    # db-init subcommand
    subparsers.add_parser(
        "db-init",
        help="Run database migrations",
    )

    # whoami subcommand
    subparsers.add_parser(
        "whoami",
        help="List users (diagnostic)",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    # Run the appropriate command
    if args.command == "db-init":
        return asyncio.run(cmd_db_init(args))
    elif args.command == "whoami":
        return asyncio.run(cmd_whoami(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
