"""TSX, CSS modules, SCSS modules, and the get_ast language override."""

from pathlib import Path

from tree_sitter import Query, QueryCursor

from mcp_server_tree_sitter.di import get_container
from mcp_server_tree_sitter.language.registry import LanguageRegistry
from mcp_server_tree_sitter.language.templates import QUERY_TEMPLATES
from mcp_server_tree_sitter.models.project import Project
from mcp_server_tree_sitter.tools.ast_operations import get_file_ast
from mcp_server_tree_sitter.tools.search import find_similar_code, query_code
from mcp_server_tree_sitter.utils.tree_sitter_helpers import parse_file_with_detection

JSX = 'export const A = () => <div className="x" />\n'
RULE = ".a { color: red; }\n"
VARIABLE = "$color: red;\n"


def _child_types(node) -> list[str]:
    types = []
    for index in range(node.child_count):
        child = node.child(index)
        if child is not None:
            types.append(child.type)
    return types


def test_tsx_parses_jsx_that_typescript_marks_as_error() -> None:
    """The same JSX source is a program under tsx and an ERROR under typescript."""
    registry = LanguageRegistry()
    tsx_root = registry.get_parser("tsx").parse(JSX.encode()).root_node
    typescript_root = registry.get_parser("typescript").parse(JSX.encode()).root_node

    assert tsx_root.has_error is False
    assert "ERROR" not in _child_types(tsx_root)
    assert typescript_root.has_error is True
    assert "ERROR" in _child_types(typescript_root)


def test_hh_header_detects_as_cpp(tmp_path: Path) -> None:
    """`.hh` stayed C++ when detection moved onto the registry."""
    path = tmp_path / "header.hh"
    path.write_text("class Header {};\n")
    registry = LanguageRegistry()
    assert registry.language_for_file(str(path)) == "cpp"
    tree, _source = parse_file_with_detection(path, None, registry)
    assert tree.root_node.has_error is False


def test_compound_suffixes_win_over_the_single_extension() -> None:
    registry = LanguageRegistry()
    assert registry.language_for_file("style.css") == "css"
    assert registry.language_for_file("styles.module.css") == "css_modules"
    assert registry.language_for_file("xmodule.css") == "css"
    assert registry.language_for_file("plain.scss") == "scss"
    assert registry.language_for_file("theme.sass") == "scss"
    assert registry.language_for_file("styles.module.scss") == "scss_modules"
    assert registry.language_for_file("test.ts") == "typescript"
    assert registry.language_for_file("component.tsx") == "tsx"
    assert registry.language_for_file("dir\\styles.module.css") == "css_modules"
    assert registry.language_for_file("dir/styles.module.scss") == "scss_modules"


def test_module_ids_parse_with_their_own_grammars() -> None:
    """css_modules uses CSS. scss_modules uses SCSS, so `$color:` is not an error."""
    registry = LanguageRegistry()
    css_modules = registry.get_parser("css_modules").parse(RULE.encode()).root_node
    scss_modules = registry.get_parser("scss_modules").parse(VARIABLE.encode()).root_node
    css_on_variable = registry.get_parser("css").parse(VARIABLE.encode()).root_node

    assert css_modules.has_error is False
    assert scss_modules.has_error is False
    assert css_on_variable.has_error is True
    assert registry._grammar_ids["css_modules"] == "css"
    assert registry._grammar_ids["scss_modules"] == "scss"

    listed = set(registry.list_available_languages())
    for language in ("tsx", "css", "scss", "css_modules", "scss_modules"):
        assert language in listed
        assert registry.is_language_available(language) is True


def test_scss_variable_template_keeps_dollar_names() -> None:
    registry = LanguageRegistry()
    source = b"$color: red;\n.btn { color: $color; composes: x; }\n"
    tree = registry.get_parser("scss_modules").parse(source)
    query = Query(registry.get_language("scss_modules"), QUERY_TEMPLATES["scss_modules"]["variables"])
    names = {
        node.text.decode()
        for node in QueryCursor(query).captures(tree.root_node)["variable.name"]
        if node.text is not None
    }
    assert names == {"$color"}


def test_tsx_jsx_template_captures_the_tag() -> None:
    registry = LanguageRegistry()
    tree = registry.get_parser("tsx").parse(JSX.encode())
    query = Query(registry.get_language("tsx"), QUERY_TEMPLATES["tsx"]["jsx"])
    names = {
        node.text.decode() for node in QueryCursor(query).captures(tree.root_node)["jsx.name"] if node.text is not None
    }
    assert names == {"div"}


def test_get_ast_language_override_parses_tsx_on_a_ts_path(tmp_path: Path) -> None:
    (tmp_path / "widget.ts").write_text(JSX)
    container = get_container()
    project = Project("tsx-override", tmp_path)
    registry = container.language_registry
    cache = container.tree_cache

    overridden = get_file_ast(project, "widget.ts", registry, cache, language="tsx")
    detected = get_file_ast(project, "widget.ts", registry, cache)

    assert overridden["language"] == "tsx"
    assert "ERROR" not in _child_types_from_dict(overridden["tree"])
    assert detected["language"] == "typescript"
    assert "ERROR" in _child_types_from_dict(detected["tree"])


def _child_types_from_dict(tree: dict) -> list[str]:
    return [child["type"] for child in tree.get("children", [])]


def test_parse_file_with_detection_uses_tsx_for_tsx_files(tmp_path: Path) -> None:
    path = tmp_path / "view.tsx"
    path.write_text(JSX)
    tree, _source = parse_file_with_detection(path, None, LanguageRegistry())
    assert tree.root_node.has_error is False
    assert "ERROR" not in _child_types(tree.root_node)


def test_project_search_does_not_mix_module_and_plain_files(tmp_path: Path) -> None:
    (tmp_path / "plain.scss").write_text(RULE)
    (tmp_path / "styles.module.scss").write_text(RULE + VARIABLE)
    (tmp_path / "styles.module.css").write_text(RULE)
    (tmp_path / "plain.css").write_text(RULE)
    nested = tmp_path / "components"
    nested.mkdir()
    (nested / "button.module.scss").write_text(RULE)
    (nested / "button.scss").write_text(RULE)
    project = Project("styles", tmp_path)
    container = get_container()
    registry = container.language_registry
    cache = container.tree_cache
    query = "(rule_set) @rule"

    def files(language: str) -> set[str]:
        return {item["file"] for item in query_code(project, query, registry, cache, language=language)}

    assert files("scss") == {"plain.scss", "components/button.scss"}
    assert files("scss_modules") == {"styles.module.scss", "components/button.module.scss"}
    assert files("css") == {"plain.css"}
    assert files("css_modules") == {"styles.module.css"}

    snippet = ".a { color: red; }"
    similar_scss = {
        item["file"] for item in find_similar_code(project, snippet, registry, cache, language="scss", threshold=0.5)
    }
    similar_modules = {
        item["file"]
        for item in find_similar_code(project, snippet, registry, cache, language="scss_modules", threshold=0.5)
    }
    assert similar_scss == {"plain.scss", "components/button.scss"}
    assert "styles.module.scss" in similar_modules
    assert "components/button.module.scss" in similar_modules
    assert "plain.scss" not in similar_modules
    assert "components/button.scss" not in similar_modules


def test_exact_module_filename_is_included_in_search(tmp_path: Path) -> None:
    """A file named module.css is a CSS module, and the search glob must find it."""
    (tmp_path / "module.css").write_text(RULE)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "module.scss").write_text(RULE)
    (tmp_path / "plain.css").write_text(RULE)
    project = Project("exact-module", tmp_path)
    container = get_container()
    registry = container.language_registry
    cache = container.tree_cache
    query = "(rule_set) @rule"

    def files(language: str) -> set[str]:
        return {item["file"] for item in query_code(project, query, registry, cache, language=language)}

    assert registry.language_for_file("module.css") == "css_modules"
    assert registry.language_for_file("nested/module.scss") == "scss_modules"
    assert files("css_modules") == {"module.css"}
    assert files("scss_modules") == {"nested/module.scss"}
    assert files("css") == {"plain.css"}
    assert files("scss") == set()
