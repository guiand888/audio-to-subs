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

    @patch('src.cli.Pipeline')
    def test_process_video_progress_flag(self, mock_pipeline_class, tmp_path):
        """Test CLI with --progress flag enables verbose progress."""
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
            '--api-key', 'test_key',
            '--progress'
        ])
        
        # Assert
        assert result.exit_code == 0
        # Verify Pipeline was initialized with verbose_progress=True
        call_kwargs = mock_pipeline_class.call_args[1]
        assert call_kwargs.get('verbose_progress') is True

    def test_validate_output_directory_success(self, tmp_path):
        """Test _validate_output_directory with valid directory."""
        # Arrange
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "subs.srt"
        
        # Act & Assert - should not raise
        from src.cli import _validate_output_directory
        _validate_output_directory(str(output_path))
        assert output_path.parent.exists()

    def test_validate_output_directory_creates_dir(self, tmp_path):
        """Test _validate_output_directory creates directory if it doesn't exist."""
        # Arrange
        output_dir = tmp_path / "new_output"
        output_path = output_dir / "subs.srt"
        
        # Act
        from src.cli import _validate_output_directory
        _validate_output_directory(str(output_path))
        
        # Assert
        assert output_dir.exists()

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_processing_success(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI batch processing with config file."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
jobs:
  - input: video1.mp4
    output: output1.srt
  - input: video2.mp4
    output: output2.srt
""")
        
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_config.validate.return_value = True
        mock_config.get_jobs.return_value = [
            {"input": "video1.mp4", "output": "output1.srt", "format": "srt"},
            {"input": "video2.mp4", "output": "output2.srt", "format": "srt"},
        ]
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_batch.return_value = {
            "video1.mp4": "output1.srt",
            "video2.mp4": "output2.srt"
        }
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 0
        mock_config_class.assert_called_once()
        mock_pipeline.process_batch.assert_called_once()

    @patch('src.cli.Pipeline')
    def test_batch_and_single_mode_conflict(self, mock_pipeline_class, tmp_path):
        """Test CLI rejects using both --config and --input."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("jobs: []")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '-i', 'video.mp4',
            '-o', 'output.srt',
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'Error' in result.output

    def test_config_with_input_output_error(self, tmp_path):
        """Test CLI rejects --config with --input or --output."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.touch()
        video_file = tmp_path / "input.mp4"
        video_file.touch()
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '-i', str(video_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 1
        assert '--config cannot be used with --input' in result.output

    def test_config_with_output_error(self, tmp_path):
        """Test CLI rejects --config with --output."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.touch()
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '-o', str(tmp_path / 'output.srt'),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 1
        assert '--config cannot be used with --input or --output' in result.output

    def test_input_file_not_found_error(self, tmp_path):
        """Test CLI handles input file not found error."""
        # Arrange
        runner = CliRunner()
        
        # Act - use non-existent file (click.Path(exists=True) will fail)
        result = runner.invoke(main, [
            '-i', str(tmp_path / 'nonexistent.mp4'),
            '-o', str(tmp_path / 'output.srt'),
            '--api-key', 'test_key'
        ])
        
        # Assert - Click validates Path(exists=True) at the option level
        assert result.exit_code != 0

    @patch('src.cli._validate_output_directory')
    @patch('src.cli.Pipeline')
    def test_output_directory_validation_error(self, mock_pipeline_class, mock_validate, tmp_path):
        """Test CLI handles output directory validation error."""
        import click
        
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        
        mock_validate.side_effect = click.ClickException("Cannot create output directory")
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.return_value = str(tmp_path / "output.srt")
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(tmp_path / 'output.srt'),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 2
        assert 'Cannot create output directory' in result.output

    @patch('src.cli.Pipeline')
    def test_pipeline_error_handling(self, mock_pipeline_class, tmp_path):
        """Test CLI handles PipelineError with specific error message."""
        from src.pipeline import PipelineError
        
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.side_effect = PipelineError("Test pipeline error")
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(tmp_path / 'output.srt'),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 1
        assert 'Test pipeline error' in result.output

    @patch('src.cli.ConfigParser')
    def test_batch_config_error_handling(self, mock_config_parser, tmp_path):
        """Test batch mode handles ConfigError."""
        from src.config_parser import ConfigError
        
        # Arrange
        runner = CliRunner(mix_stderr=True)
        config_file = tmp_path / "config.yaml"
        config_file.touch()
        
        mock_parser = MagicMock()
        mock_parser.validate.side_effect = ConfigError("Invalid config")
        mock_parser.get_jobs.return_value = []
        mock_config_parser.return_value = mock_parser
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 1
        assert 'Invalid config' in result.output

    @patch('src.cli.Pipeline')
    def test_batch_pipeline_error_handling(self, mock_pipeline_class, tmp_path):
        """Test batch mode handles PipelineError."""
        from src.pipeline import PipelineError
        
        # Arrange
        runner = CliRunner(mix_stderr=True)
        config_file = tmp_path / "config.yaml"
        config_file.write_text("jobs:\n  - input: video.mp4\n    output: output.srt\n")
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_batch.side_effect = PipelineError("Batch failed")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code == 1
        assert 'Batch failed' in result.output

    def test_missing_input_file(self, tmp_path):
        """Test CLI fails when input file doesn't exist (Click validation)."""
        # Arrange
        runner = CliRunner()
        
        # Act
        result = runner.invoke(main, [
            '-i', str(tmp_path / 'nonexistent.mp4'),
            '-o', str(tmp_path / 'output.srt'),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0



    @patch('src.cli.Pipeline')
    def test_batch_processing_without_api_key(self, mock_pipeline_class, tmp_path):
        """Test CLI batch mode requires API key."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("jobs: []")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file)
        ])
        
        # Assert
        assert result.exit_code != 0

    def test_validate_output_directory_not_writable(self, tmp_path):
        """Test _validate_output_directory fails when directory is not writable."""
        # Arrange
        # Create a directory that exists but we can't write to (simulate read-only)
        output_dir = tmp_path / "readonly"
        output_dir.mkdir()
        output_path = output_dir / "subs.srt"
        
        # On Linux, we can't easily make a directory non-writable in tests
        # So we test the error message handling path
        from src.cli import _validate_output_directory
        import click
        
        # Mock os.access to return False
        with patch('src.cli.os.access', return_value=False):
            with pytest.raises(click.ClickException, match="not writable"):
                _validate_output_directory(str(output_path))

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_processing_config_error(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI handles config errors gracefully."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml")
        
        mock_config_class.side_effect = Exception("Config error")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_processing_pipeline_error(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI handles pipeline errors in batch mode."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
jobs:
  - input: video.mp4
    output: output.srt
""")
        
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_config.validate.return_value = True
        mock_config.get_jobs.return_value = [
            {"input": "video.mp4", "output": "output.srt", "format": "srt"}
        ]
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_batch.side_effect = Exception("Batch failed")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'Error' in result.output

    @patch('src.cli.Pipeline')
    def test_single_video_api_key_required(self, mock_pipeline_class, tmp_path):
        """Test CLI requires API key for single video mode."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file)
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'API key' in result.output or 'api-key' in result.output.lower()

    @patch('src.cli.Pipeline')
    def test_single_video_no_api_key_env(self, mock_pipeline_class, tmp_path):
        """Test CLI fails when no API key in env or args for single video."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        # Act - no API key provided
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file)
        ], env={})  # Empty env
        
        # Assert
        assert result.exit_code != 0

    def test_validate_output_directory_error(self, tmp_path):
        """Test _validate_output_directory raises error when directory creation fails."""
        from src.cli import _validate_output_directory
        import click
        
        # Arrange
        output_path = tmp_path / "nonexistent" / "deep" / "path" / "output.srt"
        
        # Mock mkdir to raise OSError
        with patch('src.cli.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = OSError("Cannot create directory")
            
            # Act & Assert
            with pytest.raises(click.ClickException, match="Cannot create"):
                _validate_output_directory(str(output_path))

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_config_validation_error(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI handles config validation errors."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("jobs: []")
        
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_config.validate.side_effect = Exception("Validation failed")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_jobs_error(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI handles get_jobs errors."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("jobs: []")
        
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_config.validate.return_value = True
        mock_config.get_jobs.side_effect = Exception("Invalid jobs")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.Pipeline')
    def test_pipeline_initialization_error(self, mock_pipeline_class, tmp_path):
        """Test CLI handles pipeline initialization errors."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        mock_pipeline_class.side_effect = Exception("Pipeline init failed")
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0

    @patch('src.cli.Pipeline')
    def test_pipeline_process_error(self, mock_pipeline_class, tmp_path):
        """Test CLI handles pipeline processing errors."""
        # Arrange
        runner = CliRunner()
        video_file = tmp_path / "test.mp4"
        video_file.touch()
        output_file = tmp_path / "output.srt"
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_video.side_effect = Exception("Processing failed")
        
        # Act
        result = runner.invoke(main, [
            '-i', str(video_file),
            '-o', str(output_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'Error' in result.output

    @patch('src.cli.ConfigParser')
    @patch('src.cli.Pipeline')
    def test_batch_pipeline_error(self, mock_pipeline_class, mock_config_class, tmp_path):
        """Test CLI handles pipeline errors in batch mode."""
        # Arrange
        runner = CliRunner()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
jobs:
  - input: video.mp4
    output: output.srt
""")
        
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_config.validate.return_value = True
        mock_config.get_jobs.return_value = [
            {"input": "video.mp4", "output": "output.srt", "format": "srt"}
        ]
        
        mock_pipeline = MagicMock()
        mock_pipeline_class.return_value = mock_pipeline
        mock_pipeline.process_batch.side_effect = Exception("Batch processing failed")
        
        # Act
        result = runner.invoke(main, [
            '--config', str(config_file),
            '--api-key', 'test_key'
        ])
        
        # Assert
        assert result.exit_code != 0
        assert 'Error' in result.output