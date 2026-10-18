"""Tests for Makefile target text."""

import re
from pathlib import Path


def test_makefile_target_syntax():
    """Test that critical Makefile targets are correctly formed."""
    # Get the Makefile content
    makefile_path = Path(__file__).parent.parent / "Makefile"
    with open(makefile_path) as f:
        makefile_content = f.read()

    # Test mcp targets - they should use uv run mcp directly
    mcp_target_pattern = r"mcp-(run|dev|install):\n\t\$\(UV\) run mcp"
    mcp_targets = re.findall(mcp_target_pattern, makefile_content)

    # We should find at least 3 matches (run, dev, install)
    assert len(mcp_targets) >= 3, "Missing proper mcp invocation in Makefile targets"

    # Check for correct server module reference
    assert "$(PACKAGE).server" in makefile_content, "Server module reference is incorrect"

    # Custom test for mcp-run
    mcp_run_pattern = r"mcp-run:.*\n\t\$\(UV\) run mcp run \$\(PACKAGE\)\.server"
    assert re.search(mcp_run_pattern, makefile_content), "mcp-run target is incorrectly formed"

    # Test that help is the default target
    assert ".PHONY: all help" in makefile_content, "help is not properly declared as .PHONY"
    assert "help: show-help" in makefile_content, "help is not properly set as default target"
