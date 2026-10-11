"""Query templates for SCSS.

A `$name:` declaration is a property_name. The predicate keeps names that
start with `$`. The grammar has no variable_name node.
"""

TEMPLATES = {
    "rules": """
        (rule_set) @rule
    """,
    "variables": """
        (declaration
            (property_name) @variable.name
            (#match? @variable.name "^\\\\$")) @variable
    """,
}
