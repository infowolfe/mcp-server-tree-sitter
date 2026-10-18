"""Standalone grammar behavior using metadata and module stubs only."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_server_tree_sitter import di
from mcp_server_tree_sitter.config import ConfigurationManager, ServerConfig, update_config_from_new
from mcp_server_tree_sitter.exceptions import LanguageNotFoundError
from mcp_server_tree_sitter.language import installed, registry


@pytest.fixture(autouse=True)
def isolated_caches(monkeypatch):
    monkeypatch.setattr(installed._Discovery, "found", None)
    monkeypatch.setattr(installed, "_load_cache", {})
    monkeypatch.setattr(installed, "_scm_cache", {})
    monkeypatch.setattr(installed, "_distributions", list)


def discover(monkeypatch, *names):
    metadata = [SimpleNamespace(metadata={"Name": name}) for name in names]
    monkeypatch.setattr(installed, "_distributions", lambda: metadata)


def test_pack_hit_does_not_import_standalone(monkeypatch):
    discover(monkeypatch, "tree-sitter-python")
    language, parser = object(), object()
    importer = Mock(side_effect=AssertionError("standalone import"))
    discovery = Mock(side_effect=AssertionError("premature discovery"))
    monkeypatch.setattr(installed, "_import_module", importer)
    monkeypatch.setattr(installed, "discover_installed", discovery)
    monkeypatch.setattr(registry, "pack_get_language", Mock(return_value=language))
    monkeypatch.setattr(registry, "pack_get_parser", Mock(return_value=parser))
    languages = registry.LanguageRegistry()
    assert languages.get_language("python") is language
    assert languages.get_parser("python") is parser
    assert languages.is_language_available("python")
    importer.assert_not_called()
    discovery.assert_not_called()


def test_installed_preferred_and_parser_uses_same_language(monkeypatch):
    discover(monkeypatch, "tree-sitter-python")
    capsule, language, parser = object(), object(), object()
    importer = Mock(return_value=SimpleNamespace(language=lambda: capsule))
    ctor = Mock(return_value=language)
    monkeypatch.setattr(installed, "_import_module", importer)
    loader = installed.load_installed_language
    standalone = Mock(side_effect=lambda name: loader(name, language_ctor=ctor))
    monkeypatch.setattr(installed, "load_installed_language", standalone)
    pack_language = Mock(return_value=object())
    pack_parser = Mock(return_value=object())
    monkeypatch.setattr(registry, "pack_get_language", pack_language)
    monkeypatch.setattr(registry, "pack_get_parser", pack_parser)
    create = Mock(return_value=parser)
    monkeypatch.setattr(registry, "create_parser", create)
    languages = registry.LanguageRegistry(prefer_installed_grammars=True)
    assert languages.is_language_available("python")
    assert languages.get_language("python") is language
    assert languages.get_parser("python") is parser
    standalone.assert_called_once_with("python")
    ctor.assert_called_once_with(capsule)
    create.assert_called_once_with(language)
    pack_language.assert_not_called()
    pack_parser.assert_not_called()


def test_metadata_discovery_and_id_mapping(monkeypatch):
    discover(
        monkeypatch,
        "tree-sitter",
        "tree-sitter-language-pack",
        "requests",
        "tree-sitter-c-sharp",
        "tree-sitter-python",
        "tree-sitter-new-lang",
    )
    importer = Mock(side_effect=AssertionError("metadata must not import"))
    monkeypatch.setattr(installed, "_import_module", importer)
    assert set(installed.discover_installed()) == {"csharp", "python", "new_lang"}
    assert installed.language_id_for_distribution("tree-sitter-c_sharp") == "csharp"
    assert installed.language_id_for_distribution("tree-sitter-python") == "python"
    languages = registry.LanguageRegistry()
    assert languages.language_for_file("sample.new_lang") == "new_lang"
    assert languages.language_for_file("sample.lang") is None
    assert languages.language_for_file("sample.python") is None
    assert languages.language_for_file("sample.csharp") is None
    assert languages.language_for_file("sample.cs") == "csharp"
    assert "new_lang" in languages.list_available_languages()
    assert all(isinstance(name, str) for name in languages.list_available_languages())
    importer.assert_not_called()


def test_typescript_specific_loader_and_success_cache(monkeypatch):
    capsule, language = object(), object()
    importer = Mock(return_value=SimpleNamespace(language_typescript=lambda: capsule))
    monkeypatch.setattr(installed, "_import_module", importer)
    ctor = Mock(return_value=language)
    assert installed.load_installed_language("typescript", language_ctor=ctor) is language
    assert installed.load_installed_language("typescript", language_ctor=ctor) is language
    importer.assert_called_once_with("tree_sitter_typescript")
    ctor.assert_called_once_with(capsule)


def test_import_failure_cached_and_pack_miss_raises(monkeypatch):
    discover(monkeypatch, "tree-sitter-python")
    importer = Mock(side_effect=ImportError("broken module"))
    monkeypatch.setattr(installed, "_import_module", importer)
    ctor = Mock(side_effect=AssertionError("must not construct language"))
    for _ in range(2):
        with pytest.raises(ImportError):
            installed.load_installed_language("python", language_ctor=ctor)
    monkeypatch.setattr(registry, "pack_get_language", Mock(side_effect=LookupError("pack miss")))
    languages = registry.LanguageRegistry()
    with pytest.raises(LanguageNotFoundError):
        languages.get_language("python")
    assert not languages.is_language_available("python")
    importer.assert_called_once_with("tree_sitter_python")
    ctor.assert_not_called()


def test_config_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TS_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    for name in (
        "MCP_TS_LANGUAGE_PREFER_INSTALLED_GRAMMARS",
        "MCP_TS_LANGUAGE_PREFERRED_LANGUAGES",
        "MCP_TS_LANGUAGE__PREFERRED_LANGUAGES",
        "MCP_TS_SECURITY_ALLOWED_EXTENSIONS",
        "MCP_TS_SECURITY__ALLOWED_EXTENSIONS",
        "MCP_TS_MAX_RESULTS_DEFAULT",
    ):
        monkeypatch.delenv(name, raising=False)
    original = ServerConfig()
    new = ServerConfig()
    new.language.prefer_installed_grammars = True
    new.language.preferred_languages = ["python"]
    new.security.allowed_extensions = []
    new.max_results_default = 7
    update_config_from_new(original, new)
    new.security.excluded_dirs.append("secret")
    new.language.preferred_languages.append("go")
    assert original.language.prefer_installed_grammars is True
    assert original.language.preferred_languages == ["python"]
    assert original.security.allowed_extensions == []
    assert "secret" not in original.security.excluded_dirs
    assert original.max_results_default == 7
    serialized = ConfigurationManager(original).to_dict()
    assert serialized["language"]["prefer_installed_grammars"] is True
    assert serialized["language"]["preferred_languages"] == ["python"]
    assert serialized["security"]["allowed_extensions"] == []
    assert serialized["max_results_default"] == 7
    restored = ServerConfig(**serialized)
    assert restored.language.prefer_installed_grammars is True
    assert restored.language.preferred_languages == ["python"]
    assert restored.max_results_default == 7


def test_construction_does_not_call_container_or_discovery(monkeypatch):
    container = Mock(side_effect=AssertionError("container called during construction"))
    discovery = Mock(side_effect=AssertionError("discovery during construction"))
    monkeypatch.setattr(di, "get_container", container)
    monkeypatch.setattr(installed, "discover_installed", discovery)
    assert registry.LanguageRegistry().prefer_installed_grammars is False
    assert registry.LanguageRegistry(True).prefer_installed_grammars is True
    container.assert_not_called()
    discovery.assert_not_called()


def test_pack_parser_failure_builds_parser(monkeypatch):
    language, parser = object(), object()
    monkeypatch.setattr(registry, "pack_get_language", Mock(return_value=language))
    monkeypatch.setattr(registry, "pack_get_parser", Mock(side_effect=RuntimeError("parser failed")))
    create = Mock(return_value=parser)
    monkeypatch.setattr(registry, "create_parser", create)
    assert registry.LanguageRegistry().get_parser("python") is parser
    create.assert_called_once_with(language)


def test_pack_miss_loads_new_id_by_name(monkeypatch):
    discover(monkeypatch, "tree-sitter-new-lang")
    language = object()
    monkeypatch.setattr(registry, "pack_get_language", Mock(side_effect=LookupError("pack miss")))
    standalone = Mock(return_value=language)
    monkeypatch.setattr(installed, "load_installed_language", standalone)
    assert registry.LanguageRegistry().get_language("new_lang") is language
    standalone.assert_called_once_with("new_lang")
