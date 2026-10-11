"""Query templates for SCSS modules.

scss_modules parses with the SCSS grammar, not the CSS grammar. The id stays
separate so a search for scss does not return styles.module.scss.
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
