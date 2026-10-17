"""Service templates launch the console script with the real config path."""

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "contrib" / "systemd" / "mcp-server-tree-sitter.service"
LAUNCHD = ROOT / "contrib" / "launchd" / "mcp-server-tree-sitter.plist"
README = ROOT / "README.md"
CONFIG = "tree-sitter-mcp/config.yaml"


def test_systemd_unit_passes_config():
    """The user unit passes --config and does not rely on ~ expansion."""
    text = SYSTEMD.read_text()
    exec_lines = [line for line in text.splitlines() if line.startswith("ExecStart=")]

    assert exec_lines == [
        "ExecStart=%h/.local/bin/mcp-server-tree-sitter --config %h/.config/tree-sitter-mcp/config.yaml"
    ]
    assert all("~" not in line for line in exec_lines)
    assert CONFIG in text
    assert "tree-sitter/config.yaml" not in text.replace(CONFIG, "")


def test_launchd_plist_passes_config():
    """The user agent passes --config through a shell so $HOME can expand."""
    plist = plistlib.loads(LAUNCHD.read_bytes())
    args = plist["ProgramArguments"]
    command = " ".join(args)

    assert plist["Label"] == "com.github.infowolfe.mcp-server-tree-sitter"
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert args[0] == "/bin/sh"
    assert "--config" in command
    assert f'"$HOME/.config/{CONFIG}"' in command
    assert "tree-sitter/config.yaml" not in command.replace(CONFIG, "")


def test_readme_documents_service_templates():
    """The README section names both templates and the config file."""
    readme = README.read_text()
    section = readme.split("## Running as a service", 1)[1].split("## For Developers", 1)[0]

    assert "~/.config/tree-sitter-mcp/config.yaml" in section
    assert "contrib/systemd/mcp-server-tree-sitter.service" in section
    assert "contrib/launchd/mcp-server-tree-sitter.plist" in section
    assert "streamable-http" in section
    assert "--config" in section
