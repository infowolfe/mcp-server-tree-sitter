"""Query templates for Kotlin language."""

TEMPLATES = {
    "functions": """
        (function_declaration
            (simple_identifier) @function.name) @function.def

        (function_declaration
            (simple_identifier) @function.name
            (function_body) @function.body) @function.def
    """,
    "classes": """
        (class_declaration
            "class"
            (type_identifier) @class.name) @class.def

        (class_declaration
            "class"
            (type_identifier) @class.name
            (class_body) @class.body) @class.def

        (object_declaration
            (type_identifier) @class.name) @class.def

        (object_declaration
            (type_identifier) @class.name
            (class_body) @class.body) @class.def
    """,
    "interfaces": """
        (class_declaration
            "interface"
            (type_identifier) @interface.name) @interface.def

        (class_declaration
            "interface"
            (type_identifier) @interface.name
            (class_body) @interface.body) @interface.def
    """,
    "imports": """
        (import_header) @import

        (import_header
            (identifier) @import.id) @import.simple

        (import_header
            (import_alias
                (type_identifier) @import.alias)) @import.aliased
    """,
    "properties": """
        (property_declaration
            (variable_declaration
                (simple_identifier) @property.name)) @property.def
    """,
    "dataClasses": """
        (class_declaration
            (modifiers
                (class_modifier
                    "data" @data_class.modifier))
            (type_identifier) @data_class.name) @data_class.def
    """,
}
