"""Compile bundled query templates against tree-sitter-language-pack."""

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from mcp_server_tree_sitter.language.registry import LanguageRegistry
from mcp_server_tree_sitter.language.templates import QUERY_TEMPLATES

# APL templates are registered, but the language is not in the 1.21 manifest.
UNLOADABLE = {"apl"}


def test_every_template_compiles() -> None:
    """Every bundled template must compile. APL is the only language with no grammar.

    css_modules and scss_modules are not pack ids. The registry aliases them
    to the css and scss grammars.
    """
    registry = LanguageRegistry()
    unloadable = set()
    for language in sorted(QUERY_TEMPLATES):
        try:
            language_obj = registry.get_language(language)
        except Exception as exc:
            unloadable.add(language)
            if language not in UNLOADABLE:
                raise AssertionError(f"{language} failed to load: {exc}") from exc
            continue
        for name, source in QUERY_TEMPLATES[language].items():
            try:
                Query(language_obj, source)
            except Exception as exc:
                raise AssertionError(f"{language}.{name} failed to compile: {exc}") from exc
    assert unloadable == UNLOADABLE


def test_julia_extension_is_registered() -> None:
    """Julia templates are only reachable when .jl maps to the julia grammar."""
    assert LanguageRegistry().language_for_file("sample.jl") == "julia"


def _captures(language: str, source: str, template_names: list[str]) -> dict[str, set[str]]:
    language_obj = get_language(language)
    tree = get_parser(language).parse(source.encode())
    found: dict[str, set[str]] = {}
    for name in template_names:
        query = Query(language_obj, QUERY_TEMPLATES[language][name])
        for capture, nodes in QueryCursor(query).captures(tree.root_node).items():
            found.setdefault(capture, set()).update(node.text.decode() for node in nodes if node.text is not None)
    return found


def test_clojure_definition_captures() -> None:
    source = """
(ns demo.core)
(require 'clojure.string)
(import java.util.Date)
(use clojure.set)
(defn greet
  "Say hi."
  [name]
  (str "hi " name))
(defn- hidden [x] x)
(fn [x] x)
(defmacro when-let [binding & body] body)
(defprotocol Greet (hello [this]))
(defrecord Person [name])
(deftype Box [value])
(extend-protocol Greet Person (hello [this] name))
(swap! state inc)
(reset! state 1)
{:a 1}
#{1}
"""
    found = _captures(
        "clojure",
        source,
        ["functions", "namespaces", "imports", "macros", "protocols", "atoms", "data_structures"],
    )
    assert found["function.name"] == {"greet", "hidden"}
    assert found["namespace.name"] == {"demo.core"}
    assert found["import.module"] == {"'clojure.string", "clojure.set"}
    assert found["import.class"] == {"java.util.Date"}
    assert found["macro.name"] == {"when-let"}
    assert found["protocol.name"] == {"Greet"}
    assert found["record.name"] == {"Person"}
    assert found["type.name"] == {"Box"}
    assert found["atom.name"] == {"state"}
    assert "{:a 1}" in found["data.map"]
    assert "#{1}" in found["data.set"]
    assert "bindings" not in QUERY_TEMPLATES["clojure"]
    meta = _captures(
        "clojure",
        "(defn ^String greet [x] x)\n(defmacro ^:private m [x] x)\n(ns ^:private demo.core)\n",
        ["functions", "macros", "namespaces"],
    )
    assert meta["function.name"] == {"greet"}
    assert meta["macro.name"] == {"m"}
    assert meta["namespace.name"] == {"demo.core"}
    qualified = _captures(
        "clojure",
        "(swap! left/state inc)\n(reset! right/state 0)\n"
        "(extend-protocol demo/Greet Person)\n(defn my.ns/greet [x] x)\n",
        ["atoms", "protocols", "functions"],
    )
    assert qualified["atom.name"] == {"left/state", "right/state"}
    assert qualified["extend.protocol"] == {"demo/Greet"}
    assert qualified["function.name"] == {"my.ns/greet"}
    meta_qualified = _captures("clojure", "(swap! ^:private left/state inc)\n", ["atoms"])
    assert meta_qualified["atom.name"] == {"state"}


def test_javascript_import_captures() -> None:
    source = "import { a as b, c } from './x';\nimport * as ns from './y';\nimport d from './z';\nimport './side';\n"
    found = _captures("javascript", source, ["imports"])
    assert found["import.specifier"] == {"a", "c", "ns", "d"}
    assert found["import.alias"] == {"b"}
    assert any("./x" in item for item in found["import.source"])


def test_typescript_interface_captures() -> None:
    source = "interface Foo { a: number }\ntype Bar = { b: string }\n"
    found = _captures("typescript", source, ["interfaces"])
    assert found["interface.name"] == {"Foo"}
    assert found["alias.name"] == {"Bar"}


def test_typescript_import_captures() -> None:
    source = (
        "import { Client as Javelin } from 'javelin';\n"
        "import Sources from './audio/Sources';\n"
        "import path = require('path');\n"
    )
    found = _captures("typescript", source, ["imports"])
    assert found["import.name"] == {"Client", "Sources", "path"}
    assert found["import.alias"] == {"Javelin"}


def test_cpp_method_and_template_captures() -> None:
    source = "template<typename T> class Box {};\nclass Foo { void bar(){} void run(); };\nvoid baz(){}\n"
    found = _captures("cpp", source, ["functions", "templates"])
    assert found["function.name"] == {"baz"}
    assert found["method.name"] == {"bar", "run"}
    assert found["template.class"] == {"Box"}


def test_java_symbol_captures() -> None:
    source = (
        "import java.util.List;\n"
        "import static java.util.Collections.*;\n"
        "class C { C(){} void m(){} }\n"
        "interface I { void f(); }\n"
    )
    found = _captures("java", source, ["functions", "classes", "interfaces", "imports"])
    assert found["function.name"] == {"m"}
    assert found["constructor.name"] == {"C"}
    assert found["class.name"] == {"C"}
    assert found["interface.name"] == {"I"}
    assert found["import.name"] == {"java.util.List", "java.util.Collections"}
    assert found["import.class"] == {"List", "Collections"}
    assert found["import.wildcard"] == {"*"}


def test_kotlin_symbol_captures() -> None:
    source = (
        "import foo.bar.Baz as Q\n"
        "import foo.bar.Baz\n"
        "interface I { fun g(): Int }\n"
        "class C { fun f(x: Int): Int { return x } }\n"
        "data class D(val name: String)\n"
        "val x = 1\n"
        "fun String.foo(): Int { return length }\n"
        "object O\n"
    )
    found = _captures("kotlin", source, ["functions", "classes", "interfaces", "imports", "properties", "dataClasses"])
    assert found["function.name"] == {"g", "f", "foo"}
    assert found["class.name"] == {"C", "D", "O"}
    assert found["interface.name"] == {"I"}
    assert "I" not in found["class.name"]
    assert found["import.id"] == {"foo.bar.Baz"}
    assert found["import.alias"] == {"Q"}
    assert found["property.name"] == {"x"}
    assert found["data_class.name"] == {"D"}


def test_swift_declaration_kinds_stay_separate() -> None:
    source = (
        "import Foo\n"
        "import Foo.Bar\n"
        "class C { func g() {} }\n"
        "struct S { var x: Int }\n"
        "extension S { func h() {} }\n"
        "protocol P { func p() }\n"
    )
    found = _captures("swift", source, ["functions", "classes", "structs", "imports", "protocols", "extensions"])
    assert found["function.name"] == {"g", "h"}
    assert found["class.name"] == {"C"}
    assert found["struct.name"] == {"S"}
    assert found["extension.name"] == {"S"}
    assert found["protocol.name"] == {"P"}
    assert found["import.path"] == {"Foo", "Foo.Bar"}


def test_julia_symbol_captures() -> None:
    source = (
        "module M\n"
        "import Foo.Bar\n"
        "import Foo\n"
        "using Baz\n"
        "using Foo.Bar\n"
        "function f(x)\n"
        "  x\n"
        "end\n"
        "g(x) = x\n"
        "y = h(x)\n"
        "function Tables.columnindex(x)\n"
        "  x\n"
        "end\n"
        "Foo.bar(x) = x\n"
        "struct S\n"
        "  a\n"
        "end\n"
        "mutable struct T\n"
        "  b\n"
        "end\n"
        "macro m(x)\n"
        "  x\n"
        "end\n"
        "abstract type Animal end\n"
        "end\n"
    )
    found = _captures("julia", source, ["functions", "modules", "structs", "imports", "macros", "abstractTypes"])
    assert found["function.name"] == {"f", "g", "Tables.columnindex", "Foo.bar"}
    assert found["module.name"] == {"M"}
    assert found["struct.name"] == {"S", "T"}
    assert found["import.name"] == {"Foo.Bar", "Foo", "Baz"}
    assert found["macro.name"] == {"m"}
    assert found["abstract.name"] == {"Animal"}
