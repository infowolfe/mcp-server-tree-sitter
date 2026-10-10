"""Query templates for C#.

Adapted from Za-Pa-Al's c_sharp templates. The language id is csharp, matching
tree-sitter-language-pack, not c_sharp.
"""

TEMPLATES = {
    "classes": """
        (class_declaration
            name: (identifier) @class.name) @class.def
    """,
    "methods": """
        (method_declaration
            name: (identifier) @method.name) @method.def
    """,
    "properties": """
        (property_declaration
            name: (identifier) @property.name) @property.def
    """,
    "interfaces": """
        (interface_declaration
            name: (identifier) @interface.name) @interface.def
    """,
    "using": """
        (using_directive) @using
    """,
}
