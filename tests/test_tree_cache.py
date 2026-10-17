"""TreeCache hands out copies, and parsers are built per call."""

import threading

from tree_sitter_language_pack import get_parser

from mcp_server_tree_sitter.cache import parser_cache
from mcp_server_tree_sitter.cache.parser_cache import TreeCache
from mcp_server_tree_sitter.language.registry import LanguageRegistry


def _isolated_cache(monkeypatch) -> TreeCache:
    """A cache that does not consult the process-wide config."""
    cache = TreeCache(max_size_mb=10, ttl_seconds=300, enabled=True)
    monkeypatch.setattr(cache, "_is_cache_enabled", lambda: True)
    monkeypatch.setattr(cache, "_get_ttl_seconds", lambda: 300)
    monkeypatch.setattr(cache, "_get_max_size_mb", lambda: 10.0)
    return cache


def test_get_and_put_do_not_share_the_stored_tree(tmp_path, monkeypatch):
    """put keeps a copy, and each get returns a further copy."""
    cache = _isolated_cache(monkeypatch)
    source = b"def f():\n    return 1\n"
    path = tmp_path / "f.py"
    path.write_bytes(source)
    parsed = get_parser("python").parse(source)
    original_end = parsed.root_node.end_byte

    cache.put(path, "python", parsed, source)
    stored = cache.cache[cache._get_cache_key(path, "python")][0]
    first = cache.get(path, "python")
    second = cache.get(path, "python")

    assert first is not None
    assert second is not None
    assert stored is not parsed
    assert first[0] is not stored
    assert first[0] is not parsed
    assert second[0] is not first[0]
    assert first[0].root_node.end_byte == original_end
    assert stored.root_node.end_byte == original_end

    first[0].edit(
        start_byte=0,
        old_end_byte=0,
        new_end_byte=4,
        start_point=(0, 0),
        old_end_point=(0, 0),
        new_end_point=(0, 4),
    )

    assert stored.root_node.end_byte == original_end
    again = cache.get(path, "python")
    assert again is not None
    assert again[0] is not stored
    assert again[0].root_node.end_byte == original_end


def test_update_tree_stores_a_copy(tmp_path, monkeypatch):
    """update_tree replaces the entry with a copy of the tree it was given."""
    cache = _isolated_cache(monkeypatch)
    source = b"x = 1\n"
    path = tmp_path / "g.py"
    path.write_bytes(source)
    parsed = get_parser("python").parse(source)
    cache.put(path, "python", parsed, source)

    replacement_source = b"value = 2\n"
    replacement = get_parser("python").parse(replacement_source)
    cache.update_tree(path, "python", replacement, replacement_source)
    stored_tree, stored_source, _timestamp = cache.cache[cache._get_cache_key(path, "python")]

    assert stored_tree is not replacement
    assert stored_source == replacement_source
    assert stored_tree.root_node.end_byte == replacement.root_node.end_byte
    assert stored_tree.root_node.end_byte != parsed.root_node.end_byte
    got = cache.get(path, "python")
    assert got is not None
    assert got[0] is not stored_tree
    assert got[1] == replacement_source


def test_concurrent_gets_walk_separate_copies(tmp_path, monkeypatch):
    """Several threads can walk copies from one cached parse."""
    cache = _isolated_cache(monkeypatch)
    source = b"def f():\n    return 1\n"
    path = tmp_path / "h.py"
    path.write_bytes(source)
    cache.put(path, "python", get_parser("python").parse(source), source)
    errors: list[Exception] = []

    def walk() -> None:
        try:
            for _ in range(40):
                got = cache.get(path, "python")
                assert got is not None
                cursor = got[0].root_node.walk()
                assert cursor.node is not None
                cursor.goto_first_child()
        except Exception as exc:  # the thread reports it
            errors.append(exc)

    threads = [threading.Thread(target=walk) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


def test_get_parser_returns_a_new_parser_each_call():
    """LanguageRegistry does not reuse a Parser across calls."""
    registry = LanguageRegistry()
    assert registry.get_parser("python") is not registry.get_parser("python")


def test_shared_parser_helper_is_gone():
    """The lru_cache parser helper is not part of the package."""
    assert not hasattr(parser_cache, "get_cached_parser")
