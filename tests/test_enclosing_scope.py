"""Tests for get_enclosing_scope.

Scope expectations follow the tables adapted from Carlos Faria
(cx-carlos-faria, CxMaster), with the grammar corrections for language-pack 1.21.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from tree_sitter_language_pack import get_parser

from mcp_server_tree_sitter.api import get_language_registry, get_project_registry, get_tree_cache
from mcp_server_tree_sitter.di import get_container
from mcp_server_tree_sitter.exceptions import FileAccessError
from mcp_server_tree_sitter.language.scope_types import SCOPE_TYPES
from mcp_server_tree_sitter.tools.ast_operations import get_enclosing_scope
from tests.test_helpers import register_project_tool

PYTHON_SOURCE = """import os

X = 42

def foo():
    return 1

class Bar:
    @staticmethod
    def meth(self):
        def inner():
            return 2
        return inner

    z = 0

    def other(self):
        return 3

def outer():
    def nested():
        return 9
    return nested

def bar():
    return 4
"""

GO_SOURCE = """package p

type (
    S struct{}
    N int
)
"""

JS_SOURCE = """const a = (x) => x;
function g() { return 1; }
"""

JS_KEYWORD_SOURCE = """const f = function() { return 1; };
function g() { return 2; }
"""

TS_KEYWORD_SOURCE = """const f = function() { return 1; };
function g(): number { return 2; }
"""

C_PAREN_SOURCE = """int (foo)(int x) { return x; }
int (*id(int x))(int) { return 0; }
"""

C_SOURCE = """int foo(int x) { return x; }
int *id(int *p) { return p; }
"""

CPP_SOURCE = """class C {
  void bar() { return; }
};
int free_fn() { return 1; }
int &ref(int &v) { return v; }
"""


def _register(tmp_path: Path, name: str, filename: str, source: str) -> str:
    file_path = tmp_path / filename
    file_path.write_text(source)
    registered = register_project_tool(path=str(tmp_path), name=name)
    return os.path.relpath(file_path, registered["root_path"])


def _find(source: str, needle: str) -> tuple[int, int]:
    data = source.encode()
    start = data.find(needle.encode())
    assert start >= 0, needle
    row = data.count(b"\n", 0, start)
    line_start = data.rfind(b"\n", 0, start) + 1
    return row, start - line_start


def _at(
    project: str,
    path: str,
    source: str,
    needle: str,
    max_lines: int = 200,
) -> dict[str, Any] | None:
    row, column = _find(source, needle)
    return get_enclosing_scope(
        get_project_registry().get_project(project),
        path,
        row,
        column,
        get_language_registry(),
        get_tree_cache(),
        max_lines=max_lines,
    )


def _end(source: str, language: str) -> tuple[int, int]:
    tree = get_parser(language).parse(source.encode())
    end = tree.root_node.end_point
    return int(end[0]), int(end[1])


@pytest.fixture
def python_file(tmp_path: Path) -> tuple[str, str]:
    return "scope-python", _register(tmp_path, "scope-python", "sample.py", PYTHON_SOURCE)


def test_cursor_inside_function(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "return 1")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["type"] == "function_definition"
    assert scope["name"] == "foo"
    assert scope["truncated"] is False
    assert scope["file"] == path
    assert "def foo" in scope["text"]


def test_cursor_on_method(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "def meth")
    assert scope is not None
    assert scope["kind"] == "method"
    assert scope["type"] == "function_definition"
    assert scope["name"] == "meth"


DECORATOR_SOURCE = """@decorator
def top():
    return 1

class C:
    @staticmethod
    def f(x):
        return x
"""


def test_cursor_on_decorator_returns_the_decorated_scope(tmp_path: Path) -> None:
    project = "scope-decorator"
    path = _register(tmp_path, project, "decorated.py", DECORATOR_SOURCE)

    top = _at(project, path, DECORATOR_SOURCE, "@decorator")
    assert top is not None
    assert top["kind"] == "function"
    assert top["type"] == "function_definition"
    assert top["name"] == "top"
    assert "def top" in top["text"]

    method = _at(project, path, DECORATOR_SOURCE, "@staticmethod")
    assert method is not None
    assert method["kind"] == "method"
    assert method["type"] == "function_definition"
    assert method["name"] == "f"
    assert method["text"].startswith("def f")


def test_decorated_method(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "return inner")
    assert scope is not None
    assert scope["kind"] == "method"
    assert scope["name"] == "meth"
    assert scope["type"] == "function_definition"
    assert "def meth" in scope["text"]
    assert "return inner" in scope["text"]


def test_function_nested_in_method_stays_function(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "return 2")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["name"] == "inner"
    assert "return inner" not in scope["text"]


def test_class_body_between_methods(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "z = 0")
    assert scope is not None
    assert scope["kind"] == "class"
    assert scope["type"] == "class_definition"
    assert scope["name"] == "Bar"
    assert "def meth" in scope["text"]
    assert "def other" in scope["text"]


def test_module_blank_line_is_truncated(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = get_enclosing_scope(
        get_project_registry().get_project(project),
        path,
        1,
        0,
        get_language_registry(),
        get_tree_cache(),
        max_lines=2,
    )
    assert scope is not None
    assert scope["kind"] == "module"
    assert scope["type"] == "module"
    assert scope["name"] is None
    assert scope["truncated"] is True
    assert scope["text"] == "".join(PYTHON_SOURCE.splitlines(keepends=True)[:2])
    assert "def foo" not in scope["text"]


def test_module_max_lines_zero_is_not_truncated(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = get_enclosing_scope(
        get_project_registry().get_project(project),
        path,
        1,
        0,
        get_language_registry(),
        get_tree_cache(),
        max_lines=0,
    )
    assert scope is not None
    assert scope["kind"] == "module"
    assert scope["truncated"] is False
    assert scope["text"] == PYTHON_SOURCE


def test_nested_function_at_module_level(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "return 9")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["name"] == "nested"


def test_module_level_function_is_not_a_method(python_file: tuple[str, str]) -> None:
    project, path = python_file
    scope = _at(project, path, PYTHON_SOURCE, "return 4")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["name"] == "bar"


def test_exclusive_end_point_is_module(python_file: tuple[str, str]) -> None:
    project, path = python_file
    row, column = _end(PYTHON_SOURCE, "python")
    scope = get_enclosing_scope(
        get_project_registry().get_project(project),
        path,
        row,
        column,
        get_language_registry(),
        get_tree_cache(),
        max_lines=2,
    )
    assert scope is not None
    assert scope["kind"] == "module"
    assert scope["truncated"] is True


def test_row_past_eof_is_none(python_file: tuple[str, str]) -> None:
    project, path = python_file
    row, _column = _end(PYTHON_SOURCE, "python")
    scope = get_enclosing_scope(
        get_project_registry().get_project(project),
        path,
        row + 5,
        0,
        get_language_registry(),
        get_tree_cache(),
    )
    assert scope is None


def test_go_grouped_struct_spec_does_not_cover_alias(tmp_path: Path) -> None:
    project = "scope-go"
    path = _register(tmp_path, project, "group.go", GO_SOURCE)

    struct_scope = _at(project, path, GO_SOURCE, "S struct")
    assert struct_scope is not None
    assert struct_scope["kind"] == "class"
    assert struct_scope["type"] == "type_spec"
    assert struct_scope["name"] == "S"
    assert "N" not in struct_scope["text"]

    alias_scope = _at(project, path, GO_SOURCE, "N int")
    assert alias_scope is not None
    assert alias_scope["type"] == "source_file"
    assert alias_scope["kind"] == "module"
    assert alias_scope["name"] is None


DART_SOURCE = """void main() { print(1); }
class C {
  void m() { print(2); }
}
"""


def test_dart_function_body_uses_previous_signature(tmp_path: Path) -> None:
    project = "scope-dart"
    path = _register(tmp_path, project, "main.dart", DART_SOURCE)

    top = _at(project, path, DART_SOURCE, "print(1)")
    assert top is not None
    assert top["type"] == "function_body"
    assert top["kind"] == "function"
    assert top["name"] == "main"
    assert "void main" not in top["text"]

    method = _at(project, path, DART_SOURCE, "print(2)")
    assert method is not None
    assert method["type"] == "function_body"
    assert method["name"] == "m"

    top_signature = _at(project, path, DART_SOURCE, "void main")
    assert top_signature is not None
    assert top_signature["type"] == "function_body"
    assert top_signature["name"] == "main"
    assert "print(1)" in top_signature["text"]

    method_signature = _at(project, path, DART_SOURCE, "m()")
    assert method_signature is not None
    assert method_signature["type"] == "function_body"
    assert method_signature["name"] == "m"
    assert "class C" not in method_signature["text"]


def test_javascript_keyword_cursor_reaches_the_function(tmp_path: Path) -> None:
    project = "scope-js-keyword"
    path = _register(tmp_path, project, "keyword.js", JS_KEYWORD_SOURCE)

    expression = _at(project, path, JS_KEYWORD_SOURCE, "function()")
    assert expression is not None
    assert expression["kind"] == "function"
    assert expression["type"] == "function_expression"
    assert expression["name"] is None
    assert "return 1" in expression["text"]
    assert expression["text"] != "function"

    declaration = _at(project, path, JS_KEYWORD_SOURCE, "function g")
    assert declaration is not None
    assert declaration["kind"] == "function"
    assert declaration["type"] == "function_declaration"
    assert declaration["name"] == "g"
    assert "return 2" in declaration["text"]


def test_typescript_keyword_cursor_reaches_the_function(tmp_path: Path) -> None:
    project = "scope-ts-keyword"
    path = _register(tmp_path, project, "keyword.ts", TS_KEYWORD_SOURCE)
    expression = _at(project, path, TS_KEYWORD_SOURCE, "function()")
    assert expression is not None
    assert expression["type"] == "function_expression"
    assert expression["name"] is None
    assert "return 1" in expression["text"]


def test_c_parenthesized_declarator_name(tmp_path: Path) -> None:
    project = "scope-c-paren"
    path = _register(tmp_path, project, "paren.c", C_PAREN_SOURCE)

    simple = _at(project, path, C_PAREN_SOURCE, "return x")
    assert simple is not None
    assert simple["kind"] == "function"
    assert simple["name"] == "foo"

    nested = _at(project, path, C_PAREN_SOURCE, "return 0")
    assert nested is not None
    assert nested["kind"] == "function"
    assert nested["name"] == "id"
    assert nested["type"] == "function_definition"


def test_javascript_arrow_function(tmp_path: Path) -> None:
    project = "scope-js"
    path = _register(tmp_path, project, "arrow.js", JS_SOURCE)
    scope = _at(project, path, JS_SOURCE, "=>")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["type"] == "arrow_function"
    assert scope["name"] is None
    assert "=>" in scope["text"]


def test_c_pointer_function_name(tmp_path: Path) -> None:
    project = "scope-c"
    path = _register(tmp_path, project, "id.c", C_SOURCE)
    scope = _at(project, path, C_SOURCE, "return p")
    assert scope is not None
    assert scope["kind"] == "function"
    assert scope["name"] == "id"
    assert scope["type"] == "function_definition"


CPP_MEMBER_SOURCE = """class C {
public:
    C() {}
    ~C() {}
    friend void f() { return; }
};
void C::out() {}
void ns::h() { return; }
int free_fn() { return 1; }
"""


def test_cpp_constructors_destructors_and_qualified_names(tmp_path: Path) -> None:
    project = "scope-cpp-members"
    path = _register(tmp_path, project, "members.cpp", CPP_MEMBER_SOURCE)

    constructor = _at(project, path, CPP_MEMBER_SOURCE, "C() {}")
    assert constructor is not None
    assert constructor["kind"] == "method"
    assert constructor["name"] == "C"

    destructor = _at(project, path, CPP_MEMBER_SOURCE, "~C() {}")
    assert destructor is not None
    assert destructor["kind"] == "method"
    assert destructor["name"] == "~C"

    friend = _at(project, path, CPP_MEMBER_SOURCE, "friend void")
    assert friend is not None
    assert friend["kind"] == "function"
    assert friend["name"] == "f"

    outlined = _at(project, path, CPP_MEMBER_SOURCE, "C::out")
    assert outlined is not None
    assert outlined["kind"] == "method"
    assert outlined["name"] == "out"

    namespaced = _at(project, path, CPP_MEMBER_SOURCE, "ns::h")
    assert namespaced is not None
    assert namespaced["kind"] == "function"
    assert namespaced["name"] == "h"

    free = _at(project, path, CPP_MEMBER_SOURCE, "return 1")
    assert free is not None
    assert free["kind"] == "function"
    assert free["name"] == "free_fn"


def test_cpp_operator_name(tmp_path: Path) -> None:
    source = "class Foo {\n  bool operator==(const Foo& other) { return true; }\n};\n"
    project = "scope-cpp-op"
    path = _register(tmp_path, project, "op.cpp", source)
    scope = _at(project, path, source, "operator==")
    assert scope is not None
    assert scope["kind"] == "method"
    assert scope["name"] == "operator=="
    assert scope["type"] == "function_definition"


def test_cpp_method_and_reference_declarator(tmp_path: Path) -> None:
    project = "scope-cpp"
    path = _register(tmp_path, project, "methods.cpp", CPP_SOURCE)

    method = _at(project, path, CPP_SOURCE, "return;")
    assert method is not None
    assert method["kind"] == "method"
    assert method["name"] == "bar"
    assert method["type"] == "function_definition"

    free = _at(project, path, CPP_SOURCE, "return 1")
    assert free is not None
    assert free["kind"] == "function"
    assert free["name"] == "free_fn"

    reference = _at(project, path, CPP_SOURCE, "return v")
    assert reference is not None
    assert reference["kind"] == "function"
    assert reference["name"] == "ref"


def test_oversize_file_is_rejected_before_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = "scope-oversize"
    path = _register(tmp_path, project, "big.py", "x = 1\n")
    project_obj = get_project_registry().get_project(project)
    language_registry = get_language_registry()
    tree_cache = get_tree_cache()

    first = get_enclosing_scope(project_obj, path, 0, 0, language_registry, tree_cache)
    assert first is not None

    def fail_parse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("parse_file must not run after the size check fails")

    monkeypatch.setattr("mcp_server_tree_sitter.tools.ast_operations.parse_file", fail_parse)

    config_manager = get_container().config_manager
    original = config_manager.get_config().security.max_file_size_mb
    config_manager.update_value("security.max_file_size_mb", 0)
    try:
        with pytest.raises(FileAccessError):
            get_enclosing_scope(project_obj, path, 0, 0, language_registry, tree_cache)
    finally:
        config_manager.update_value("security.max_file_size_mb", original)


SWIFT_SOURCE = """struct S {
    func f(x: Int) -> Int { return x }
    var x: Int { return 2 }
}
class C {
    func m() { print(1) }
    init() { print(2) }
}
extension S {
    func g() { print(3) }
}
func free() { print(4) }
"""


def test_swift_column_zero_and_computed_members(tmp_path: Path) -> None:
    project = "scope-swift"
    path = _register(tmp_path, project, "sample.swift", SWIFT_SOURCE)

    free = _at(project, path, SWIFT_SOURCE, "func free")
    assert free is not None
    assert free["kind"] == "function"
    assert free["type"] == "function_declaration"
    assert free["name"] == "free"
    assert "struct S" not in free["text"]

    extension = _at(project, path, SWIFT_SOURCE, "extension S")
    assert extension is not None
    assert extension["kind"] == "class"
    assert extension["type"] == "class_declaration"
    assert extension["name"] == "S"
    assert "func free" not in extension["text"]

    computed = _at(project, path, SWIFT_SOURCE, "return 2")
    assert computed is not None
    assert computed["kind"] == "function"
    assert computed["type"] == "computed_property"
    assert computed["name"] == "x"
    assert "struct S" not in computed["text"]

    initializer = _at(project, path, SWIFT_SOURCE, "print(2)")
    assert initializer is not None
    assert initializer["kind"] == "function"
    assert initializer["type"] == "init_declaration"
    assert initializer["name"] == "init"
    assert "class C" not in initializer["text"]


DART_MEMBER_SOURCE = """void main() { print(1); }
class C {
  void m() { print(2); }
  C() { print(3); }
  C.named() { print(4); }
  int get x { return 5; }
}
"""


def test_dart_constructors_and_getters_are_named(tmp_path: Path) -> None:
    project = "scope-dart-members"
    path = _register(tmp_path, project, "members.dart", DART_MEMBER_SOURCE)

    constructor = _at(project, path, DART_MEMBER_SOURCE, "print(3)")
    assert constructor is not None
    assert constructor["kind"] == "function"
    assert constructor["type"] == "function_body"
    assert constructor["name"] == "C"

    named = _at(project, path, DART_MEMBER_SOURCE, "print(4)")
    assert named is not None
    assert named["name"] == "C.named"
    assert named["type"] == "function_body"

    getter = _at(project, path, DART_MEMBER_SOURCE, "return 5")
    assert getter is not None
    assert getter["name"] == "x"
    assert getter["type"] == "function_body"

    constructor_signature = _at(project, path, DART_MEMBER_SOURCE, "C.named")
    assert constructor_signature is not None
    assert constructor_signature["name"] == "C.named"
    assert constructor_signature["type"] == "function_body"


JULIA_SOURCE = """module M
function foo(x)
    return x
end
struct S
    a::Int
end
f(y) = y + 1
end
"""


def test_julia_names_and_short_function(tmp_path: Path) -> None:
    project = "scope-julia"
    path = _register(tmp_path, project, "sample.jl", JULIA_SOURCE)

    function = _at(project, path, JULIA_SOURCE, "return x")
    assert function is not None
    assert function["kind"] == "function"
    assert function["type"] == "function_definition"
    assert function["name"] == "foo"
    assert "struct S" not in function["text"]

    struct = _at(project, path, JULIA_SOURCE, "a::Int")
    assert struct is not None
    assert struct["kind"] == "class"
    assert struct["type"] == "struct_definition"
    assert struct["name"] == "S"

    short = _at(project, path, JULIA_SOURCE, "y + 1")
    assert short is not None
    assert short["kind"] == "function"
    assert short["type"] == "assignment"
    assert short["name"] == "f"
    assert "function foo" not in short["text"]


def test_cpp_template_line_uses_the_declaration(tmp_path: Path) -> None:
    source = """namespace ns {}
void ns::h() { return; }
class C {
  friend void pal() { return; }
  void bar() { return; }
};
template<class T>
void C::templ(T v) { return; }
"""
    project = "scope-cpp-template"
    path = _register(tmp_path, project, "templ.cpp", source)

    template = _at(project, path, source, "template<class T>")
    assert template is not None
    assert template["kind"] == "method"
    assert template["type"] == "function_definition"
    assert template["name"] == "templ"
    assert "namespace ns" not in template["text"]

    body = _at(project, path, source, "T v")
    assert body is not None
    assert body["name"] == "templ"
    assert body["kind"] == "method"


def test_kotlin_getter_uses_the_property_name(tmp_path: Path) -> None:
    source = """class Box {
    val name: String
        get() = "x"
}
"""
    project = "scope-kotlin-getter"
    path = _register(tmp_path, project, "box.kt", source)
    getter = _at(project, path, source, "get()")
    assert getter is not None
    assert getter["kind"] == "function"
    assert getter["type"] == "getter"
    assert getter["name"] == "name"
    assert "class Box" not in getter["text"]


def test_rust_impl_uses_the_type_name(tmp_path: Path) -> None:
    source = """trait Tr { fn f(&self); }
struct S { x: i32 }
impl Tr for S {
    fn f(&self) {}
}
impl S {
    fn get(&self) -> i32 { self.x }
}
"""
    project = "scope-rust-impl"
    path = _register(tmp_path, project, "lib.rs", source)

    trait_impl = _at(project, path, source, "impl Tr")
    assert trait_impl is not None
    assert trait_impl["kind"] == "class"
    assert trait_impl["type"] == "impl_item"
    assert trait_impl["name"] == "S"

    plain = _at(project, path, source, "impl S")
    assert plain is not None
    assert plain["kind"] == "class"
    assert plain["type"] == "impl_item"
    assert plain["name"] == "S"
    assert plain["text"] != trait_impl["text"]


def test_scope_tables_drop_rejected_node_types() -> None:
    def types_for(language: str) -> set[str]:
        found: set[str] = set()
        for node_types in SCOPE_TYPES[language].values():
            found.update(node_types)
        return found

    assert "interface_declaration" not in types_for("kotlin")
    assert "kotlin_file" not in types_for("kotlin")
    assert "source_file" in types_for("kotlin")

    assert "method_definition" not in types_for("cpp")
    assert "struct_declaration" not in types_for("swift")
    assert "mutable_struct_definition" not in types_for("julia")
    assert "function_signature" not in types_for("dart")
    assert "function_body" in types_for("dart")
    assert "function" not in types_for("javascript")
    assert "function" not in types_for("typescript")
    assert "type_declaration" not in types_for("go")
    assert "type_spec" in types_for("go")
    assert "struct_declaration" in types_for("csharp")
    assert "ruby" not in SCOPE_TYPES
    assert "php" not in SCOPE_TYPES
