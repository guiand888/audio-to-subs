"""Tests for CLI module."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from click.testing import CliRunner
from src.cli import main


class TestCLI:
    """Test command-line interface."""

    def test_cli_help(self):
        """Test CLI help message."""
        # Arrange
        runner = CliRunner()
        
        # Act
        result = runner.invoke(main, ['--help'])
        
        # Assert
        assert result.exit_code == 0
        assert 'Usage:' in result.output
        assert '--input' in result.output or '-i' in result.output
        assert '--output' in result.output or '-o' in result.output

    @patch('src.cli.Pipeline')
    def test_process_video_success(self, mock_pipeline_class, tmp_path):
        """Test successful video processing via CLI."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.return_value = str(output_file)
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 0
        mock_pipeline.process_video.assert_called_once()

    @patch('src.cli.Pipeline')
    def test_process_video_missing_input(self, mock_pipeline_class):
        """Test CLI fails when input file not specified."""
        # Arrange
        runner = CliRunner()
        
        # Act
        result = runner.invoke(main, [
            '-o', 'output.srt',
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.Pipeline')
    def test_process_video_missing_output(self, mock_pipeline_class):
        """Test CLI fails when output file not specified."""
        # Arrange
        runner = CliRunner()
        
        # Act
        result = runner.invoke(main, [
            '-i', 'input.mp4',
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.Pipeline')
    def test_process_video_missing_api_key(self, mock_pipeline_class, tmp_path):
        """Test CLI fails when API key not provided."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', 'output.srt'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.Pipeline')
    def test_process_video_api_key_from_env(self, mock_pipeline_class, tmp_path):
        """Test CLI reads API key from environment variable."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.return_value = str(output_file)
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file)
        ], env={'MISTRAL_API_KEY': 'env_key'})
        
        # Assert
        assert result.exit_code == 0
        mock_pipeline_class.assert_called()

    @patch('src.cli.Pipeline')
    def test_process_video_pipeline_error(self, mock_pipeline_class, tmp_path):
        """Test CLI handles pipeline errors gracefully."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.side_effect = Exception("Pipeline failed")
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', 'output.srt',
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'error' in result.output.lower() or 'failed' in result.output.lower()

    @patch('src.cli.Pipeline')
    def test_process_video_progress_output(self, mock_pipeline_class, tmp_path):
        """Test CLI shows progress messages."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.return_value = str(output_file)
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 0
        # Check that Pipeline was initialized with progress callback
        mock_pipeline_class.assert_called_once()
        call_kwargs = mock_pipeline_class.call_args[1]
        assert 'progress_callback' in call_kwargs or 'progress' in str(call_kwargs).lower()

    def test_cli_version(self):
        """Test CLI version flag."""
        # Arrange
        runner = CliRunner()
        
        # Act
        result = runner.invoke(main, ['--version'])
        
        # Assert
        assert result.exit_code == 0
        assert 'audio-to-subs' in result.output.lower() or '0.' in result.output