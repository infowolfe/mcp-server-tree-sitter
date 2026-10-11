"""Query templates for CSS."""

TEMPLATES = {
    "rules": """
        (rule_set) @rule
    """,
    "classes": """
        (class_selector
            (class_name) @class.name) @class
    """,
}
