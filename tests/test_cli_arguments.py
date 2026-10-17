"""Tests for command-line argument handling."""

import subprocess
import sys

from mcp_server_tree_sitter.server import main


def test_help_flag_does_not_start_server():
    """Test that --help flag prints help and doesn't start the server."""
    # Use subprocess to test the actual command
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server_tree_sitter", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Check that it exited successfully
    assert result.returncode == 0

    # Check that the help text was printed
    assert "MCP Tree-sitter Server" in result.stdout
    assert "--help" in result.stdout
    assert "--config" in result.stdout
    assert "--server" in result.stdout
    assert "--socket" in result.stdout

    # Server should not have started - no startup messages
    assert "Starting MCP Tree-sitter Server" not in result.stdout


def test_version_flag_exits_without_starting_server():
    """Test that --version shows version and exits without starting the server."""
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server_tree_sitter", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Check that it exited successfully
    assert result.returncode == 0

    # Check that the version was printed
    assert "mcp-server-tree-sitter version" in result.stdout

    # Server should not have started
    assert "Starting MCP Tree-sitter Server" not in result.stdout


def test_direct_script_help_flag():
    """The console-script entry point prints help and does not start the server."""
    from click.testing import CliRunner

    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "MCP Tree-sitter Server" in result.output
    assert "--config" in result.output
    assert "--mount-path" in result.output
    assert "Starting MCP Tree-sitter Server" not in result.output


def test_entry_point_implementation():
    """The console script is a Click command and exposes the service flags."""
    import click

    assert isinstance(main, click.Command)
    opts = {opt for param in main.params for opt in param.opts}
    assert "--version" in opts
    assert "--config" in opts
    assert "--transport" in opts
    assert "--host" in opts
    assert "--port" in opts
    assert "--mount-path" in opts
    assert "--server" in opts
    assert "--socket" in opts
