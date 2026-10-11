"""Query templates for Clojure.

Adapted from franks42. A pattern is omitted when it does not parse, or when
its captures include delimiter tokens. Name captures skip leading metadata.
A qualified symbol with no metadata keeps its namespace.
"""


def _symbol_name(capture: str) -> str:
    """Capture a symbol's name without a leading metadata span.

    A qualified symbol such as left/state is one sym_lit. Its text is the
    qualified name only when metadata is absent. Metadata lives in that same
    span, so a metadata-bearing symbol captures the sym_name child.
    """
    return (
        "[\n"
        f'          (sym_lit . (sym_ns) "/" (sym_name)) @{capture}\n'
        f'          (sym_lit (meta_lit)+ . (sym_ns) "/" (sym_name) @{capture})\n'
        f"          (sym_lit (meta_lit)+ . (sym_name) @{capture})\n"
        f"          (sym_lit . (sym_name) @{capture})\n"
        "        ]"
    )


TEMPLATES = {
    "functions": f"""
        ;; Public function definitions
        (list_lit
          .
          (sym_lit) @_defn
          (#eq? @_defn "defn")
          .
          {_symbol_name("function.name")}
          .
          (str_lit)? @function.docstring
          .
          (vec_lit)? @function.params) @function.def

        ;; Private function definitions
        (list_lit
          .
          (sym_lit) @_defn
          (#eq? @_defn "defn-")
          .
          {_symbol_name("function.name")}
          .
          (str_lit)? @function.docstring
          .
          (vec_lit)? @function.params) @function.def

        ;; Lambda functions
        (list_lit
          .
          (sym_lit) @_fn
          (#any-of? @_fn "fn" "fn*")
          .
          (vec_lit)? @function.params) @function.def
    """,
    "namespaces": f"""
        ;; Namespace declarations
        (list_lit
          .
          (sym_lit) @_ns
          (#eq? @_ns "ns")
          .
          {_symbol_name("namespace.name")}) @namespace.def
    """,
    "imports": """
        ;; Require statements
        (list_lit
          .
          (sym_lit) @_require
          (#eq? @_require "require")
          .
          (_) @import.module) @import

        ;; Import statements
        (list_lit
          .
          (sym_lit) @_import
          (#eq? @_import "import")
          .
          (_) @import.class) @import

        ;; Use statements
        (list_lit
          .
          (sym_lit) @_use
          (#eq? @_use "use")
          .
          (_) @import.module) @import
    """,
    "macros": f"""
        ;; Macro definitions
        (list_lit
          .
          (sym_lit) @_defmacro
          (#eq? @_defmacro "defmacro")
          .
          {_symbol_name("macro.name")}
          .
          (str_lit)? @macro.docstring
          .
          (vec_lit)? @macro.params) @macro.def
    """,
    "protocols": f"""
        ;; Protocol definitions
        (list_lit
          .
          (sym_lit) @_defprotocol
          (#eq? @_defprotocol "defprotocol")
          .
          {_symbol_name("protocol.name")}) @protocol.def

        ;; Record definitions
        (list_lit
          .
          (sym_lit) @_defrecord
          (#eq? @_defrecord "defrecord")
          .
          {_symbol_name("record.name")}) @record.def

        ;; Type definitions
        (list_lit
          .
          (sym_lit) @_deftype
          (#eq? @_deftype "deftype")
          .
          {_symbol_name("type.name")}) @type.def

        ;; Protocol implementations
        (list_lit
          .
          (sym_lit) @_extend
          (#any-of? @_extend "extend-protocol" "extend-type")
          .
          {_symbol_name("extend.protocol")}) @extend.def
    """,
    "data_structures": """
        ;; Vectors
        (vec_lit) @data.vector

        ;; Lists (function calls)
        (list_lit) @data.list

        ;; Maps
        (map_lit) @data.map

        ;; Sets
        (set_lit) @data.set
    """,
    "atoms": f"""
        ;; Atom operations
        (list_lit
          .
          (sym_lit) @_atom_op
          (#any-of? @_atom_op "swap!" "reset!" "compare-and-set!")
          .
          {_symbol_name("atom.name")}) @atom.operation
    """,
}
