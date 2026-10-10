"""Scope node types for get_enclosing_scope.

Adapted from the scope tables by Carlos Faria (cx-carlos-faria, CxMaster).
Node types that tree-sitter-language-pack 1.21 rejects are omitted. A flat
node-type map is not enough for Python methods or Go struct specs; those
rules are applied while walking the tree.
"""

from typing import Dict, Mapping, Optional, Tuple

# Kind lists are most specific first: method, function, class, then module.
ScopeTable = Mapping[str, Tuple[str, ...]]

SCOPE_TYPES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "python": {
        "function": ("function_definition",),
        "class": ("class_definition",),
        "module": ("module",),
    },
    "javascript": {
        "method": ("method_definition",),
        # The keyword token named "function" is not a scope. It does not
        # wrap the body, so a cursor on that word must keep walking to
        # function_expression or function_declaration.
        "function": (
            "function_declaration",
            "function_expression",
            "arrow_function",
        ),
        "class": ("class_declaration",),
        "module": ("program",),
    },
    "typescript": {
        "method": ("method_definition",),
        "function": (
            "function_declaration",
            "function_expression",
            "arrow_function",
        ),
        "class": ("class_declaration",),
        "module": ("program",),
    },
    "go": {
        # method_declaration stays kind function. Struct scope is a type_spec,
        # and only when that spec's type is struct_type.
        "function": ("function_declaration", "method_declaration"),
        "class": ("type_spec",),
        "module": ("source_file",),
    },
    "rust": {
        "function": ("function_item",),
        "class": ("struct_item", "impl_item", "trait_item"),
        "module": ("source_file",),
    },
    "java": {
        "function": ("method_declaration", "constructor_declaration"),
        "class": ("class_declaration", "interface_declaration"),
        "module": ("program",),
    },
    "kotlin": {
        # No interface_declaration: class and interface are both class_declaration.
        # The file root is source_file, not kotlin_file.
        "function": ("function_declaration", "getter", "setter"),
        "class": ("class_declaration",),
        "module": ("source_file",),
    },
    "c": {
        "function": ("function_definition",),
        "class": ("struct_specifier",),
        "module": ("translation_unit",),
    },
    "cpp": {
        # No method_definition. Method kind is decided from the declarator
        # and whether the function sits in a class or struct.
        "function": ("function_definition",),
        "class": ("class_specifier", "struct_specifier"),
        "module": ("translation_unit",),
    },
    "swift": {
        # No struct_declaration. class, struct, and extension are class_declaration.
        # Pack 1.21 emits computed_property and init_declaration. The getter and
        # setter names are kept for grammars that still use them.
        "function": (
            "function_declaration",
            "computed_property",
            "init_declaration",
            "computed_getter",
            "computed_setter",
        ),
        "class": ("class_declaration",),
        "module": ("source_file",),
    },
    "julia": {
        # Mutable and immutable structs are both struct_definition.
        # module_definition is a nested module, not the file root.
        "function": ("function_definition",),
        "class": ("struct_definition",),
        "module": ("source_file", "module_definition"),
    },
    "csharp": {
        "function": (
            "method_declaration",
            "constructor_declaration",
            "local_function_statement",
        ),
        "class": ("class_declaration", "struct_declaration", "interface_declaration"),
        "module": ("compilation_unit",),
    },
    "dart": {
        # function_signature does not contain the body. The body is the sibling
        # function_body. The name sits on the preceding signature.
        "function": ("function_body",),
        "class": (
            "class_definition",
            "mixin_declaration",
            "enum_declaration",
            "extension_declaration",
        ),
        "module": ("program",),
    },
}

_KIND_ORDER: Tuple[str, ...] = ("method", "function", "class", "module")


def kind_for_node_type(language: str, node_type: str) -> Optional[str]:
    """Return the table kind for a node type, before Python, Go, and C++ refinements."""
    table: Optional[ScopeTable] = SCOPE_TYPES.get(language)
    if table is None:
        return None
    for kind in _KIND_ORDER:
        node_types = table.get(kind, ())
        if node_type in node_types:
            return kind
    return None
