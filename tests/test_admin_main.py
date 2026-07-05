"""Tests for the admin CLI (set-password, whoami, argument parsing)."""

import argparse
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from audio_to_subs.admin.__main__ import cmd_set_password, cmd_whoami, main
from audio_to_subs.auth.passwords import verify_password
from audio_to_subs.db.models import User


@pytest.fixture(autouse=True)
def _point_admin_cli_at_test_db(monkeypatch, tmp_path):
    """admin/__main__.py's get_async_session() defaults to a hardcoded DSN;
    point it at the per-test DB used by the rest of the suite so cmd_*
    functions operate on the same database the test asserts against.
    """
    import audio_to_subs.db.session as db_session
    from audio_to_subs.api.settings import get_settings

    monkeypatch.setattr(
        db_session, "DEFAULT_ASYNC_DSN", get_settings().DATABASE_URL
    )


class TestCmdSetPassword:
    """Test the set-password admin subcommand."""

    @pytest.mark.asyncio
    async def test_creates_new_user_when_username_not_found(self, sync_session):
        args = argparse.Namespace(username="newuser")

        with patch("getpass.getpass", side_effect=["newpassword123", "newpassword123"]):
            exit_code = await cmd_set_password(args)

        assert exit_code == 0

        user = sync_session.execute(
            select(User).where(User.username == "newuser")
        ).scalar_one()
        assert verify_password("newpassword123", user.password_hash)

    @pytest.mark.asyncio
    async def test_updates_existing_user_password(self, sync_session):
        # conftest's autouse fixture seeds an "admin" user already.
        args = argparse.Namespace(username="admin")

        with patch("getpass.getpass", side_effect=["rotatedpassword456", "rotatedpassword456"]):
            exit_code = await cmd_set_password(args)

        assert exit_code == 0

        user = sync_session.execute(
            select(User).where(User.username == "admin")
        ).scalar_one()
        assert verify_password("rotatedpassword456", user.password_hash)

    @pytest.mark.asyncio
    async def test_mismatched_passwords_returns_error(self, capsys):
        args = argparse.Namespace(username="admin")

        with patch("getpass.getpass", side_effect=["password1", "password2"]):
            exit_code = await cmd_set_password(args)

        assert exit_code == 1
        assert "do not match" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_defaults_username_to_admin_when_not_specified(self, sync_session):
        args = argparse.Namespace(username=None)

        with patch("getpass.getpass", side_effect=["newpass789", "newpass789"]):
            exit_code = await cmd_set_password(args)

        assert exit_code == 0
        user = sync_session.execute(
            select(User).where(User.username == "admin")
        ).scalar_one()
        assert verify_password("newpass789", user.password_hash)


class TestCmdWhoami:
    """Test the whoami admin subcommand."""

    @pytest.mark.asyncio
    async def test_lists_seeded_admin_user(self, capsys):
        args = argparse.Namespace()

        exit_code = await cmd_whoami(args)

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "admin" in output


class TestMainArgumentParsing:
    """Test main()'s subcommand dispatch."""

    def test_no_command_prints_help_and_returns_1(self, capsys):
        exit_code = main([])
        assert exit_code == 1

    def test_unrecognized_command_raises_systemexit(self):
        with pytest.raises(SystemExit):
            main(["not-a-real-command"])

    def test_dispatches_whoami(self):
        with patch(
            "audio_to_subs.admin.__main__.cmd_whoami", new_callable=AsyncMock
        ) as mock_whoami:
            mock_whoami.return_value = 0
            exit_code = main(["whoami"])

        assert exit_code == 0
        mock_whoami.assert_called_once()

    def test_dispatches_set_password_with_username(self):
        with patch(
            "audio_to_subs.admin.__main__.cmd_set_password", new_callable=AsyncMock
        ) as mock_set_password:
            mock_set_password.return_value = 0
            exit_code = main(["set-password", "--username", "someone"])

        assert exit_code == 0
        called_args = mock_set_password.call_args[0][0]
        assert called_args.username == "someone"
