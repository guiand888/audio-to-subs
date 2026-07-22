"""Tests for the admin CLI (db-init, whoami, argument parsing)."""

import argparse
from unittest.mock import AsyncMock, patch

import pytest

from audio_to_subs.admin.__main__ import cmd_whoami, main


@pytest.fixture(autouse=True)
def _point_admin_cli_at_test_db(monkeypatch, tmp_path):
    """admin/__main__.py's get_async_session() defaults to a hardcoded DSN;
    point it at the per-test DB used by the rest of the suite so cmd_*
    functions operate on the same database the test asserts against.
    """
    import audio_to_subs.db.session as db_session
    from audio_to_subs.api.settings import get_settings

    monkeypatch.setattr(db_session, "DEFAULT_ASYNC_DSN", get_settings().DATABASE_URL)


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
