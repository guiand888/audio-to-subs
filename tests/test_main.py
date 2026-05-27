"""Tests for __main__.py entry point."""

from unittest.mock import patch
from src.cli import main as cli_main


class TestMain:
    """Test __main__.py entry point."""

    def test_main_calls_cli_main(self):
        """Test that __main__.py calls cli.main()."""
        # Import the __main__ module
        import src.__main__ as main_module
        
        # Verify that cli.main is what gets called
        assert hasattr(main_module, 'main')
        assert main_module.main is cli_main

    def test_main_execution(self):
        """Test that __main__.py has correct main function."""
        # Import the __main__ module
        import src.__main__ as main_module
        
        # Verify main exists and is callable
        assert hasattr(main_module, 'main')
        assert callable(main_module.main)
        # Verify it's the same as cli.main
        from src.cli import main as cli_main
        assert main_module.main is cli_main
