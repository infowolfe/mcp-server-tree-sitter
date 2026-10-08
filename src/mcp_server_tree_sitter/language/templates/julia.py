"""Query templates for Julia language."""

TEMPLATES = {
    "functions": """
        (function_definition
            (signature
                (call_expression
                    (identifier) @function.name))) @function.def

        (function_definition
            (signature
                (call_expression
                    (field_expression) @function.name))) @function.def

        (function_definition
            (signature
                (call_expression
                    (identifier) @function.name
                    (argument_list) @function.params))
            (block) @function.body) @function.def

        (assignment
            . (call_expression
                (identifier) @function.name)) @function.short_def

        (assignment
            . (call_expression
                (field_expression) @function.name)) @function.short_def
    """,
    "modules": """
        (module_definition
            name: (identifier) @module.name
            (block) @module.body) @module.def
    """,
    "structs": """
        (struct_definition
            (type_head
                (identifier) @struct.name)
            (block) @struct.body) @struct.def
    """,
    "imports": """
        (import_statement) @import

        (import_statement
            (import_path) @import.name) @import.simple

        (import_statement
            (identifier) @import.name) @import.simple

        (using_statement) @import

        (using_statement
            (import_path) @import.name) @import.simple

        (using_statement
            (identifier) @import.name) @import.simple
    """,
    "macros": """
        (macro_definition
            (signature
                (call_expression
                    (identifier) @macro.name))
            (block) @macro.body) @macro.def
    """,
    "abstractTypes": """
        (abstract_definition
            (type_head
                (identifier) @abstract.name)) @abstract.def
    """,
}
