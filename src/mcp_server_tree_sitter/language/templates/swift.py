"""Query templates for Swift language."""

TEMPLATES = {
    "functions": """
        (function_declaration
            name: (simple_identifier) @function.name) @function.def

        (function_declaration
            name: (simple_identifier) @function.name
            body: (function_body) @function.body) @function.def
    """,
    "classes": """
        (class_declaration
            "class"
            name: (type_identifier) @class.name) @class.def

        (class_declaration
            "class"
            name: (type_identifier) @class.name
            body: (class_body) @class.body) @class.def
    """,
    "structs": """
        (class_declaration
            "struct"
            name: (type_identifier) @struct.name) @struct.def

        (class_declaration
            "struct"
            name: (type_identifier) @struct.name
            body: (class_body) @struct.body) @struct.def
    """,
    "imports": """
        (import_declaration) @import

        (import_declaration
            (identifier) @import.path) @import.simple
    """,
    "protocols": """
        (protocol_declaration
            name: (type_identifier) @protocol.name) @protocol.def

        (protocol_declaration
            name: (type_identifier) @protocol.name
            body: (protocol_body) @protocol.body) @protocol.def
    """,
    "extensions": """
        (class_declaration
            "extension"
            name: (user_type
                (type_identifier) @extension.name)) @extension.def

        (class_declaration
            "extension"
            name: (user_type
                (type_identifier) @extension.name)
            body: (class_body) @extension.body) @extension.def
    """,
}
