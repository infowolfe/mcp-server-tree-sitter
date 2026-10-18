"""Tests for the shared content-addressed analysis cache."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

from mcp_server_tree_sitter.cache.content_cache import ContentCache
from mcp_server_tree_sitter.config import ServerConfig, update_config_from_env
from mcp_server_tree_sitter.di import get_container
from mcp_server_tree_sitter.language.query_templates import get_query_template
from mcp_server_tree_sitter.models.project import Project
from mcp_server_tree_sitter.tools import analysis as analysis_module
from mcp_server_tree_sitter.tools.analysis import (
    analyze_code_complexity,
    extract_symbols,
    find_dependencies,
)
from tests.test_helpers import temp_config


def _result_files(root: Path) -> list[Path]:
    version = root / "v1"
    if not version.is_dir():
        return []
    found = []
    for shard in version.iterdir():
        if not shard.is_dir() or len(shard.name) != 2:
            continue
        found.extend(
            entry
            for entry in shard.iterdir()
            if entry.is_file() and not entry.name.startswith(".") and len(entry.name) == 64
        )
    return found


def test_default_directories_use_tree_sitter_mcp(monkeypatch, tmp_path):
    """Cache and config both live under a tree-sitter-mcp directory."""
    monkeypatch.delenv("MCP_TS_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    from mcp_server_tree_sitter.cache.content_cache import default_cache_dir
    from mcp_server_tree_sitter.config import get_default_config_path

    assert default_cache_dir() == tmp_path / ".cache" / "tree-sitter-mcp"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    assert default_cache_dir() == tmp_path / "xdg-cache" / "tree-sitter-mcp"

    config_path = tmp_path / ".config" / "tree-sitter-mcp" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("log_level: INFO\n", encoding="utf-8")
    assert get_default_config_path() == config_path


def test_cache_dir_env_sets_directory(monkeypatch):
    """MCP_TS_CACHE_DIR is the shared cache directory."""
    monkeypatch.setenv("MCP_TS_CACHE_DIR", "/tmp/mcp-ts-cache-example")
    config = ServerConfig()
    update_config_from_env(config)
    assert config.cache.directory == "/tmp/mcp-ts-cache-example"


def test_round_trip_and_shared_bytes(tmp_path):
    """A second cache instance reads the stored result, and identical bytes share one file."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    payload = {"functions": [{"name": "alpha"}]}

    assert cache.get(source, "symbols", "python", "ident") is None
    cache.put(source.read_bytes(), "symbols", "python", "ident", payload)
    assert cache.get(source, "symbols", "python", "ident") == payload

    other = ContentCache(root=tmp_path)
    assert other.get(source, "symbols", "python", "ident") == payload
    assert other.hits == 1
    assert other.content_reads == 1

    copy = tmp_path / "b.py"
    copy.write_bytes(source.read_bytes())
    reads_before = other.content_reads
    files_before = _result_files(tmp_path)
    assert other.get(copy, "symbols", "python", "ident") == payload
    assert other.content_reads == reads_before + 1
    assert _result_files(tmp_path) == files_before

    entry = files_before[0]
    assert entry.parent.name == entry.name[:2]
    assert len(entry.parent.name) == 2


def test_edit_leaves_the_previous_result(tmp_path):
    """A changed file stores a new result and leaves the old bytes cached."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    previous = _result_files(tmp_path)

    source.write_text("def beta():\n    return 2\n", encoding="utf-8")
    assert cache.get(source, "symbols", "python", "ident") is None
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "beta"})
    current = _result_files(tmp_path)

    assert set(previous).issubset(set(current))
    assert len(current) == len(previous) + 1
    assert cache.get(source, "symbols", "python", "ident") == {"name": "beta"}


def test_matching_stat_does_not_reread(tmp_path):
    """A matching mtime and size reuses the content hash."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    assert cache.get(source, "symbols", "python", "ident") is None
    baseline = cache.content_reads
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    assert cache.content_reads == baseline

    assert cache.get(source, "symbols", "python", "ident") == {"name": "alpha"}
    assert cache.content_reads == baseline

    later = time.time() + 30
    os.utime(source, (later, later))
    assert cache.get(source, "symbols", "python", "ident") == {"name": "alpha"}
    assert cache.content_reads == baseline + 1
    assert len(_result_files(tmp_path)) == 1


def test_operations_are_separate_entries(tmp_path):
    """Symbols and dependencies for one file do not share a result file."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"kind": "symbols"})
    cache.put(source.read_bytes(), "dependencies", "python", "ident", {"kind": "dependencies"})
    assert len(_result_files(tmp_path)) == 2
    assert cache.get(source, "symbols", "python", "ident") == {"kind": "symbols"}
    assert cache.get(source, "dependencies", "python", "ident") == {"kind": "dependencies"}


def test_disabled_cache_does_not_write(tmp_path):
    """The instance flag and cache.enabled both keep the disk cache closed."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.set_enabled(False)
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    assert cache.get(source, "symbols", "python", "ident") is None
    assert _result_files(tmp_path) == []

    cache.set_enabled(True)
    with temp_config(**{"cache.enabled": False}):
        cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
        assert cache.get(source, "symbols", "python", "ident") is None
    assert _result_files(tmp_path) == []


def test_container_starts_with_config_cache_enabled(monkeypatch, tmp_path):
    """A new container copies cache.enabled onto both caches at construction."""
    monkeypatch.setenv("MCP_TS_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("MCP_TS_CACHE_ENABLED", "false")
    from mcp_server_tree_sitter.di import DependencyContainer

    fresh = DependencyContainer()
    assert fresh.get_config().cache.enabled is False
    assert fresh.content_cache.enabled is False
    assert fresh.tree_cache.enabled is False


def test_invalidate_for_a_file_drops_only_that_note(tmp_path):
    """A file clear forgets that stat note and leaves shared result files."""
    cache = ContentCache(root=tmp_path)
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    second.write_text("def beta():\n    return 2\n", encoding="utf-8")
    cache.put(first.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    cache.put(second.read_bytes(), "symbols", "python", "ident", {"name": "beta"})
    assert cache.get(first, "symbols", "python", "ident") == {"name": "alpha"}
    assert cache.get(second, "symbols", "python", "ident") == {"name": "beta"}
    reads = cache.content_reads

    cache.invalidate(first)

    assert cache.get(first, "symbols", "python", "ident") == {"name": "alpha"}
    assert cache.content_reads == reads + 1
    assert cache.get(second, "symbols", "python", "ident") == {"name": "beta"}
    assert cache.content_reads == reads + 1
    assert len(_result_files(tmp_path)) == 2


def test_invalidate_clears_shared_results(tmp_path):
    """A full clear drops every stat note and every result file."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    assert cache.get(source, "symbols", "python", "ident") == {"name": "alpha"}
    stamp = tmp_path / "v1" / "trim.txt"
    stamp.write_text("1", encoding="utf-8")

    cache.invalidate()

    assert cache._notes == {}
    assert _result_files(tmp_path) == []
    assert stamp.read_text(encoding="utf-8") == "1"
    assert cache.get(source, "symbols", "python", "ident") is None


def test_stat_notes_stay_bounded(tmp_path, monkeypatch):
    """The stat-note table drops the oldest path once it passes the cap."""
    from mcp_server_tree_sitter.cache import content_cache as content_cache_module

    monkeypatch.setattr(content_cache_module, "NOTE_LIMIT", 2)
    cache = ContentCache(root=tmp_path)
    paths = []
    for name in ("a.py", "b.py", "c.py"):
        path = tmp_path / name
        path.write_text(f"def {name[0]}():\n    return 1\n", encoding="utf-8")
        cache.get(path, "symbols", "python", "ident")
        paths.append(path)
    assert len(cache._notes) == 2

    cache.get(paths[0], "symbols", "python", "ident")
    reads = cache.content_reads
    cache.get(paths[2], "symbols", "python", "ident")
    assert cache.content_reads == reads
    assert len(cache._notes) == 2
    assert os.path.realpath(paths[1]) not in cache._notes


def test_api_clear_cache_forwards_to_content_cache(monkeypatch):
    """The API clear drops content-cache state along with parse trees."""
    from mcp_server_tree_sitter import api

    tree = MagicMock()
    content = MagicMock()
    container = MagicMock()
    container.content_cache = content
    monkeypatch.setattr(api, "get_tree_cache", lambda: tree)
    monkeypatch.setattr(api, "get_container", lambda: container)

    assert api.clear_cache()["status"] == "success"
    tree.invalidate.assert_called_once_with()
    content.invalidate.assert_called_once_with()


def test_corrupt_entry_is_a_miss(tmp_path):
    """A result that is not JSON is a miss."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    entry = _result_files(tmp_path)[0]
    entry.write_text("not-json", encoding="utf-8")
    assert cache.get(source, "symbols", "python", "ident") is None


def test_touch_refreshes_hourly(tmp_path):
    """A read refreshes a result older than an hour and leaves a newer one alone."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    entry = _result_files(tmp_path)[0]

    aged = time.time() - 7200
    os.utime(entry, (aged, aged))
    assert cache.get(source, "symbols", "python", "ident") == {"name": "alpha"}
    assert time.time() - entry.stat().st_mtime < 10

    recent = time.time() - 1800
    os.utime(entry, (recent, recent))
    assert cache.get(source, "symbols", "python", "ident") == {"name": "alpha"}
    assert abs(entry.stat().st_mtime - recent) < 1


def test_trim_drops_unused_files(tmp_path):
    """Daily cleanup deletes results that nobody has read for five days."""
    cache = ContentCache(root=tmp_path)
    source = tmp_path / "a.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    cache.put(source.read_bytes(), "symbols", "python", "ident", {"name": "alpha"})
    other = tmp_path / "b.py"
    other.write_text("def beta():\n    return 2\n", encoding="utf-8")
    cache.put(other.read_bytes(), "symbols", "python", "ident", {"name": "beta"})
    stale, fresh = _result_files(tmp_path)
    old = time.time() - (6 * 86400)
    os.utime(stale, (old, old))

    version = tmp_path / "v1"
    (version / "trim.txt").write_text("0", encoding="utf-8")
    cache._trim_checked_at = 0
    cache.maybe_trim()

    remaining = _result_files(tmp_path)
    assert stale not in remaining
    assert fresh in remaining
    assert (version / "trim.txt").exists()

    os.utime(fresh, (old, old))
    cache.maybe_trim()
    assert fresh in _result_files(tmp_path)

    lock = version / "trim.lock"
    lock.write_text("held", encoding="utf-8")
    (version / "trim.txt").write_text("0", encoding="utf-8")
    cache._trim_checked_at = 0
    cache.maybe_trim()
    assert fresh in _result_files(tmp_path)

    expired = time.time() - 7200
    os.utime(lock, (expired, expired))
    cache._trim_checked_at = 0
    cache.maybe_trim()
    assert _result_files(tmp_path) == []


def test_store_uses_the_parsed_bytes_when_the_path_changes(tmp_path, monkeypatch):
    """A path replaced after the parse is stored under the parsed bytes."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    source = project_dir / "demo.py"
    original = "def alpha():\n    return 1\n"
    replacement = "def beta():\n    return 2\n"
    source.write_text(original, encoding="utf-8")
    project = Project("parsed-bytes", project_dir)
    registry = get_container().language_registry
    real_parse = analysis_module.parse_with_cached_tree

    def replace_after_parse(path, language, language_obj, tree_cache=None):
        tree, parsed = real_parse(path, language, language_obj, tree_cache)
        Path(path).write_text(replacement, encoding="utf-8")
        return tree, parsed

    monkeypatch.setattr(analysis_module, "parse_with_cached_tree", replace_after_parse)
    first = extract_symbols(project, "demo.py", registry)
    assert [item["name"] for item in first["functions"]] == ["alpha"]

    monkeypatch.setattr(analysis_module, "parse_with_cached_tree", real_parse)
    second = extract_symbols(project, "demo.py", registry)
    assert [item["name"] for item in second["functions"]] == ["beta"]

    symbol_types = ["functions", "classes", "imports"]
    queries = {}
    for symbol_type in symbol_types:
        template = get_query_template("python", symbol_type)
        if template:
            queries[symbol_type] = template
    identity = analysis_module._symbol_identity("python", registry, symbol_types, False, queries)
    cache = get_container().content_cache
    stored = cache.get(source, "symbols", "python", identity, original.encode())
    assert stored is not None
    assert [item["name"] for item in stored["functions"]] == ["alpha"]
    current = cache.get(source, "symbols", "python", identity)
    assert current is not None
    assert [item["name"] for item in current["functions"]] == ["beta"]


def test_complexity_reuses_the_tree_it_just_parsed(tmp_path, monkeypatch):
    """A cold complexity call parses once and reuses that tree for its symbol counts."""
    from mcp_server_tree_sitter.utils import tree_sitter_helpers

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    source = project_dir / "demo.py"
    source.write_text(
        "import os\n\ndef greet(name):\n    if name:\n        return name\n",
        encoding="utf-8",
    )
    project = Project("one-parse", project_dir)
    registry = get_container().language_registry
    real_parse = tree_sitter_helpers.parse_source
    counts = {"outer": 0, "inner": 0}

    def outer(source_bytes, parser):
        counts["outer"] += 1
        return real_parse(source_bytes, parser)

    def inner(source_bytes, parser):
        counts["inner"] += 1
        return real_parse(source_bytes, parser)

    monkeypatch.setattr(tree_sitter_helpers, "parse_source", outer)
    monkeypatch.setattr(analysis_module, "parse_source", inner)
    result = analyze_code_complexity(project, "demo.py", registry)
    assert counts["outer"] == 1
    assert counts["inner"] == 0
    assert result["function_count"] == 1
    assert result["cyclomatic_complexity"] >= 2


def test_second_process_reuses_derived_results(tmp_path):
    """Another process returns symbols, dependencies, and complexity without parsing."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    source = project_dir / "demo.py"
    source.write_text(
        "import os\n\ndef greet(name):\n    if name:\n        return name\n    return os.name\n",
        encoding="utf-8",
    )
    project = Project("content-cache-demo", project_dir)
    language_registry = get_container().language_registry
    cache_root = get_container().content_cache._resolve_root()
    before = set(_result_files(cache_root))

    symbols = extract_symbols(project, "demo.py", language_registry)
    dependencies = find_dependencies(project, "demo.py", language_registry)
    complexity = analyze_code_complexity(project, "demo.py", language_registry)
    added = set(_result_files(cache_root)) - before
    # Complexity stores its own function/class symbol result beside the three calls.
    assert len(added) == 4
    assert any(item["name"] == "greet" for item in symbols["functions"])

    env = os.environ.copy()
    env["MCP_TS_LOG_LEVEL"] = "ERROR"
    env["MCP_TS_CONTENT_CACHE_PROJECT"] = str(project_dir)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import os
from pathlib import Path

from mcp_server_tree_sitter.di import get_container
from mcp_server_tree_sitter.models.project import Project
from mcp_server_tree_sitter.tools import analysis

parses = {"n": 0}
original = analysis.parse_with_cached_tree

def wrapped(*args, **kwargs):
    parses["n"] += 1
    return original(*args, **kwargs)

analysis.parse_with_cached_tree = wrapped
project = Project("content-cache-demo", Path(os.environ["MCP_TS_CONTENT_CACHE_PROJECT"]))
registry = get_container().language_registry
symbols = analysis.extract_symbols(project, "demo.py", registry)
dependencies = analysis.find_dependencies(project, "demo.py", registry)
complexity = analysis.analyze_code_complexity(project, "demo.py", registry)
cache = get_container().content_cache
print(json.dumps({
    "parses": parses["n"],
    "hits": cache.hits,
    "misses": cache.misses,
    "reads": cache.content_reads,
    "symbols": symbols,
    "dependencies": dependencies,
    "complexity": complexity,
}))
""",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["parses"] == 0
    assert payload["hits"] == 3
    assert payload["misses"] == 0
    assert payload["reads"] == 1
    assert payload["symbols"] == json.loads(json.dumps(symbols))
    assert payload["dependencies"] == json.loads(json.dumps(dependencies))
    assert payload["complexity"] == json.loads(json.dumps(complexity))
    assert set(_result_files(cache_root)) - before == added
