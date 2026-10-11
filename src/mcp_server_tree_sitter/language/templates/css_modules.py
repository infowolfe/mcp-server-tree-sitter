"""Query templates for CSS modules.

css_modules parses with the CSS grammar. The id stays separate so a search for
css does not return styles.module.css.
"""

TEMPLATES = {
    "classes": """
        (class_selector
            (class_name) @class.name) @class
    """,
    "rules": """
        (rule_set) @rule
    """,
}
