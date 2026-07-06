"""Admin CLI for audio_to_subs.

Subcommands: set-password, db-init, whoami
"""

import argparse
import asyncio
import getpass
import logging
import sys
from collections.abc import Sequence

from sqlalchemy import select

from audio_to_subs.auth.passwords import hash_password
from audio_to_subs.db.models import User
from audio_to_subs.db.session import get_async_session

logger = logging.getLogger(__name__)


async def cmd_set_password(args: argparse.Namespace) -> int:
    """Set admin password."""
    username = args.username or "admin"

    # Get password securely
    password = getpass.getpass(f"Enter password for '{username}': ")
    password_confirm = getpass.getpass(f"Confirm password for '{username}': ")

    if password != password_confirm:
        print("Error: Passwords do not match", file=sys.stderr)
        return 1

    # Get or create user
    async with get_async_session() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if user is None:
            # Create new user
            user = User(username=username, password_hash=hash_password(password))
            session.add(user)
            await session.commit()
            print(f"Created user '{username}'")
        else:
            # Update existing user
            user.password_hash = hash_password(password)
            await session.commit()
            print(f"Updated password for user '{username}'")

    return 0


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

    # set-password subcommand
    set_password_parser = subparsers.add_parser(
        "set-password",
        help="Set admin password",
    )
    set_password_parser.add_argument(
        "--username",
        default=None,
        help="Username (default: admin)",
    )

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
    if args.command == "set-password":
        return asyncio.run(cmd_set_password(args))
    elif args.command == "db-init":
        return asyncio.run(cmd_db_init(args))
    elif args.command == "whoami":
        return asyncio.run(cmd_whoami(args))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
